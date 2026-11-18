#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from commission import RULE_VERSION, CommissionStore, split_net_output, tier_rate


class CommissionRuleTests(unittest.TestCase):
    def test_tier_rates_use_integer_fractions_and_halve_after_l3(self):
        self.assertEqual((1, 20), tier_rate(1))
        self.assertEqual((3, 10), tier_rate(1, genesis=True))
        self.assertEqual((1, 50), tier_rate(2))
        self.assertEqual((1, 100), tier_rate(3))
        self.assertEqual((1, 200), tier_rate(4))
        self.assertEqual((1, 400), tier_rate(5))
        self.assertEqual((1, 800), tier_rate(6))

    def test_split_preserves_every_atomic_unit(self):
        ancestors = [
            {"uid": "sv_l1", "role": "user", "wallet": "iron-l1"},
            {"uid": "sv_l2", "role": "user", "wallet": "iron-l2"},
            {"uid": "sv_l3", "role": "user", "wallet": "iron-l3"},
            {"uid": "sv_l4", "role": "user", "wallet": "iron-l4"},
            {"uid": "sv_l5", "role": "user", "wallet": "iron-l5"},
            {"uid": "sv_l6", "role": "user", "wallet": "iron-l6"},
        ]
        result = split_net_output(1_000_000, ancestors, producer_uid="sv_miner")
        self.assertEqual(RULE_VERSION, result["ruleVersion"])
        self.assertEqual(
            [50_000, 20_000, 10_000, 5_000, 2_500, 1_250],
            [item["amountAtomic"] for item in result["allocations"]],
        )
        self.assertEqual(88_750, result["allocatedAtomic"])
        self.assertEqual(911_250, result["producerRetainedAtomic"])
        self.assertEqual(
            1_000_000,
            result["allocatedAtomic"] + result["producerRetainedAtomic"],
        )
        self.assertEqual("accrued_not_paid", result["allocations"][0]["paymentStatus"])

    def test_genesis_direct_rate_is_thirty_percent(self):
        result = split_net_output(
            1_000_000,
            [{"uid": "sv_genesis", "role": "genesis", "wallet": "iron-g"}],
            producer_uid="sv_miner",
        )
        self.assertEqual(300_000, result["allocatedAtomic"])
        self.assertEqual(700_000, result["producerRetainedAtomic"])

    def test_rounding_remainder_stays_with_producer(self):
        result = split_net_output(
            1,
            [{"uid": "sv_l%d" % tier, "role": "user", "wallet": ""} for tier in range(1, 8)],
            producer_uid="sv_miner",
        )
        self.assertEqual(0, result["allocatedAtomic"])
        self.assertEqual(1, result["producerRetainedAtomic"])
        self.assertTrue(all(item["amountAtomic"] == 0 for item in result["allocations"]))
        self.assertEqual("address_required", result["allocations"][0]["paymentStatus"])

    def test_deep_chain_cannot_expand_total_liability(self):
        ancestors = [
            {"uid": "sv_l%d" % tier, "role": "user", "wallet": "iron"}
            for tier in range(1, 65)
        ]
        amount = 10 ** 15
        normal = split_net_output(amount, ancestors, producer_uid="sv_miner")
        self.assertLessEqual(normal["allocatedAtomic"], amount * 9 // 100)
        genesis = split_net_output(
            amount,
            [dict(ancestors[0], role="genesis")] + ancestors[1:],
            producer_uid="sv_miner",
        )
        self.assertLessEqual(genesis["allocatedAtomic"], amount * 34 // 100)

    def test_invalid_amount_and_duplicate_relationship_are_rejected(self):
        for amount in (-1, True, 1.5, "1.5"):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    split_net_output(amount, [], producer_uid="sv_miner")
        with self.assertRaises(ValueError):
            split_net_output(
                100,
                [{"uid": "sv_same"}, {"uid": "sv_same"}],
                producer_uid="sv_miner",
            )
        with self.assertRaises(ValueError):
            split_net_output(
                100,
                [{"uid": "sv_miner"}],
                producer_uid="sv_miner",
            )


class CommissionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CommissionStore(os.path.join(self.temp.name, "commission.db"))
        self.ancestors = [
            {"uid": "sv_l1", "role": "user", "wallet": "iron-l1"},
            {"uid": "sv_l2", "role": "user", "wallet": ""},
        ]

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def event(**changes):
        value = {
            "eventId": "IRON:tx-confirmed:0",
            "chain": "IRON",
            "asset": "IRON",
            "txid": "tx-confirmed",
            "amountAtomic": 1_000_000,
            "precision": 8,
            "status": "finality",
            "category": "pool",
            "verification": "full",
            "internal": False,
            "change": False,
        }
        value.update(changes)
        return value

    def test_settlement_is_idempotent_and_records_unpaid_entitlements(self):
        first = self.store.settle_event(
            self.event(), self.ancestors, producer_uid="sv_miner", observed_at=100
        )
        second = self.store.settle_event(
            self.event(), self.ancestors, producer_uid="sv_miner", observed_at=101
        )
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        entries = self.store.list_entries(self.event()["eventId"])
        self.assertEqual(3, len(entries))
        self.assertEqual(1_000_000, sum(item["amountAtomic"] for item in entries))
        self.assertEqual(50_000, entries[0]["amountAtomic"])
        self.assertEqual("accrued_not_paid", entries[0]["paymentStatus"])
        self.assertEqual("address_required", entries[1]["paymentStatus"])
        self.assertEqual(930_000, entries[-1]["amountAtomic"])
        self.assertEqual("retention", entries[-1]["entryKind"])
        self.assertTrue(all(item["paymentStatus"] != "paid" for item in entries))

    def test_reorg_appends_reversals_without_deleting_history(self):
        event_id = self.event()["eventId"]
        self.store.settle_event(
            self.event(), self.ancestors, producer_uid="sv_miner", observed_at=100
        )
        first = self.store.reverse_event(event_id, observed_at=200)
        second = self.store.reverse_event(event_id, observed_at=201)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        entries = self.store.list_entries(event_id)
        self.assertEqual(6, len(entries))
        self.assertEqual(3, sum(item["entryKind"] == "reversal" for item in entries))
        self.assertEqual(0, sum(item["amountAtomic"] for item in entries))
        self.assertTrue(all(item["amountAtomic"] >= 0 for item in entries[:3]))
        self.assertTrue(all(item["amountAtomic"] <= 0 for item in entries[3:]))
        self.assertTrue(all(item["reversalOf"] for item in entries[3:]))

    def test_reversal_without_prior_settlement_is_a_noop(self):
        result = self.store.reverse_event("IRON:missing:0", observed_at=200)
        self.assertFalse(result["created"])
        self.assertEqual([], self.store.list_entries("IRON:missing:0"))

    def test_unconfirmed_or_unverified_events_never_create_entitlements(self):
        invalid_events = [
            self.event(status="pending"),
            self.event(status="reorg"),
            self.event(verification="limited"),
            self.event(category="other"),
            self.event(internal=True),
            self.event(change=True),
            self.event(amountAtomic=0),
        ]
        for event in invalid_events:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    self.store.settle_event(
                        event, self.ancestors, producer_uid="sv_miner", observed_at=100
                    )
        self.assertEqual([], self.store.list_entries(self.event()["eventId"]))


if __name__ == "__main__":
    unittest.main()
