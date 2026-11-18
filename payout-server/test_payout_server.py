#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import http.client
import json
import os
import tempfile
import threading
import unittest

from commission import CommissionStore
from payout_adapters import PayoutAdapter
from payout_server import (
    PayoutService,
    create_http_server,
    load_chain_configs,
)
from payout_store import DEFAULT_DB_PATH, PayoutStore, format_atomic


class FakeFullAdapter(PayoutAdapter):
    verification_level = "full"

    def __init__(self, result=None):
        self.result = result or {"observations": [], "quotes": []}
        self.error = None
        self.calls = 0

    def collect(self, config):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class UnverifiedAdapter(PayoutAdapter):
    def __init__(self, result):
        self.result = result

    def collect(self, config):
        return self.result


class PayoutTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "payouts.db")
        self.store = PayoutStore(self.db_path)
        self.now = 1000

    def tearDown(self):
        self.temp_dir.cleanup()

    def config(self, chain="KAS", **overrides):
        value = {
            "chain": chain,
            "asset": chain,
            "network": chain.lower() + "-test-fixture",
            "address": chain.lower() + "-public-fixture-1234567890abcdef",
            "disclosure": "masked",
            "adapter": chain.lower() + "-fixture",
        }
        value.update(overrides)
        return value

    def observation(self, txid="tx-pool-1", **overrides):
        value = {
            "chain": "KAS",
            "asset": "KAS",
            "txid": txid,
            "outputIndex": "0",
            "amountAtomic": 100,
            "precision": 2,
            "blockHeight": 10,
            "blockTime": 100,
            "observedAt": 100,
            "confirmations": 12,
            "finality": "finalized",
            "status": "finality",
            "source": "fixture-a",
            "category": "pool",
            "verification": "full",
            "quoteId": None,
            "evidence": {
                "key": "evidence-a",
                "url": "https://explorer.invalid/" + txid,
            },
            "cursor": None,
        }
        value.update(overrides)
        return value

    def quote(self, quote_id="quote-kas", **overrides):
        value = {
            "quoteId": quote_id,
            "asset": "KAS",
            "currency": "USDT",
            "pair": "KAS/USDT",
            "path": ["KAS/USDT"],
            "rate": "2.5",
            "source": "fixture-quote",
            "quoteTime": 100,
            "observedAt": 100,
        }
        value.update(overrides)
        return value

    def service(
        self, configs=None, adapters=None, timezone="UTC",
        commission_store=None, commission_resolver=None,
    ):
        return PayoutService(
            store=self.store,
            configs=configs if configs is not None else [self.config()],
            adapters=adapters or {},
            now=lambda: self.now,
            timezone=timezone,
            commission_store=commission_store,
            commission_resolver=commission_resolver,
        )

    @staticmethod
    def asset(snapshot, chain):
        return next(item for item in snapshot["assets"] if item["chain"] == chain)


class StoreTests(PayoutTestCase):
    def test_default_database_is_non_public_path(self):
        self.assertEqual(DEFAULT_DB_PATH, "/var/lib/stonevast/payouts/payouts.db")

    def test_multiple_sources_add_evidence_without_duplicating_event(self):
        first = self.observation()
        second = self.observation(
            source="fixture-b",
            observedAt=101,
            evidence={"key": "evidence-b", "url": "https://other.invalid/tx-pool-1"},
        )
        event_id = self.store.record_observation(first)
        self.assertEqual(self.store.record_observation(second), event_id)

        events = self.store.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["amountAtomic"], 100)
        self.assertEqual(len(self.store.list_evidence(event_id)), 2)
        self.assertEqual(len(self.store.list_observations(event_id)), 2)

    def test_conflicting_evidence_cannot_change_atomic_amount(self):
        self.store.record_observation(self.observation())
        with self.assertRaises(ValueError):
            self.store.record_observation(self.observation(
                source="fixture-b",
                amountAtomic=101,
                evidence={"key": "evidence-b", "url": "https://other.invalid/tx-pool-1"},
            ))
        self.assertEqual(self.store.list_events()[0]["amountAtomic"], 100)

    def test_pending_finality_reorg_and_reverted_are_audited(self):
        event_id = None
        for observed_at, status in ((1, "pending"), (2, "finality"), (3, "reorg"), (4, "reverted")):
            event_id = self.store.record_observation(self.observation(
                observedAt=observed_at,
                status=status,
                finality=status,
                confirmations=0 if status != "finality" else 20,
            ))
            self.assertEqual(self.store.get_event(event_id)["status"], status)

        event = self.store.get_event(event_id)
        self.assertEqual(event["firstObservedAt"], 1)
        self.assertEqual(event["lastObservedAt"], 4)
        self.assertEqual(event["stateChangedAt"], 4)
        self.assertEqual(len(self.store.list_observations(event_id)), 4)

    def test_older_observation_does_not_roll_back_newer_finality(self):
        event_id = self.store.record_observation(self.observation(observedAt=200))
        self.store.record_observation(self.observation(
            observedAt=100,
            status="pending",
            finality="pending",
            confirmations=0,
        ))
        event = self.store.get_event(event_id)
        self.assertEqual(event["status"], "finality")
        self.assertEqual(event["lastObservedAt"], 200)

    def test_atomic_amounts_reject_float_bool_and_negative_values(self):
        for invalid in (1.5, True, -1, "1.5"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.store.record_observation(self.observation(
                        txid="tx-" + str(invalid),
                        amountAtomic=invalid,
                    ))
        self.store.record_observation(self.observation(amountAtomic="100"))
        self.assertEqual(self.store.list_events()[0]["amountAtomic"], 100)
        self.assertEqual(format_atomic(123456789, 8), "1.23456789")
        self.assertEqual(format_atomic(100, 8), "0.000001")

    def test_cursor_is_saved_per_chain_and_source(self):
        self.store.record_observation(self.observation(cursor="cursor-7"))
        self.assertEqual(self.store.get_cursor("KAS", "fixture-a"), "cursor-7")


class AggregationTests(PayoutTestCase):
    def test_only_full_final_pool_enters_confirmed_and_pending(self):
        cases = (
            ("pool-final", "pool", "finality", "full", 100),
            ("pool-pending", "pool", "pending", "full", 40),
            ("pro-final", "pro", "finality", "full", 50),
            ("self-final", "self", "finality", "full", 60),
            ("unknown-final", "unknown", "finality", "full", 70),
            ("other-final", "other", "finality", "full", 80),
            ("pool-reorg", "pool", "reorg", "full", 90),
            ("pool-reverted", "pool", "reverted", "full", 25),
        )
        for txid, category, status, verification, amount in cases:
            self.store.record_observation(self.observation(
                txid=txid,
                category=category,
                status=status,
                finality=status,
                verification=verification,
                amountAtomic=amount,
            ))
        self.store.record_observation(self.observation(
            txid="internal-transfer", internal=True, amountAtomic=500,
        ))
        self.store.record_observation(self.observation(
            txid="change-output", change=True, amountAtomic=600,
        ))

        asset = self.asset(self.service().get_snapshot(), "KAS")
        self.assertEqual(asset["confirmedAtomic"], "100")
        self.assertEqual(asset["pendingAtomic"], "40")
        self.assertEqual(asset["confirmed"], "1")
        self.assertEqual(asset["pending"], "0.4")

    def test_different_assets_are_never_added_together(self):
        self.store.record_observation(self.observation(amountAtomic=100, precision=2))
        self.store.record_observation(self.observation(
            chain="QUAN", asset="QUAN", txid="tx-quan", amountAtomic=200, precision=8,
        ))
        snapshot = self.service([self.config("KAS"), self.config("QUAN")]).get_snapshot()
        self.assertEqual(self.asset(snapshot, "KAS")["confirmedAtomic"], "100")
        self.assertEqual(self.asset(snapshot, "QUAN")["confirmedAtomic"], "200")
        self.assertNotIn("confirmedAtomic", snapshot)
        self.assertNotIn("totalAtomic", snapshot)

    def test_missing_quotes_return_none_and_partial_then_use_exact_path(self):
        self.store.record_observation(self.observation(amountAtomic=100, precision=2))
        service = self.service()

        reference = self.asset(service.get_snapshot(), "KAS")["reference"]
        self.assertIsNone(reference["usdt"])
        self.assertIsNone(reference["cny"])
        self.assertEqual(reference["status"], "partial")

        self.store.record_quote(self.quote())
        reference = self.asset(service.get_snapshot(), "KAS")["reference"]
        self.assertEqual(reference["usdt"], "2.5")
        self.assertIsNone(reference["cny"])
        self.assertEqual(reference["status"], "partial")

        self.store.record_quote(self.quote(
            quote_id="quote-cny",
            asset="USDT",
            currency="CNY",
            pair="USDT/CNY",
            path=["USDT/CNY"],
            rate="7.0",
        ))
        snapshot = service.get_snapshot()
        reference = self.asset(snapshot, "KAS")["reference"]
        self.assertEqual(reference["usdt"], "2.5")
        self.assertEqual(reference["cny"], "17.5")
        self.assertEqual(reference["status"], "ok")
        self.assertEqual(reference["quoteIds"], ["quote-kas", "quote-cny"])
        self.assertEqual(len(snapshot["quotes"]), 2)

    def test_iron_limited_total_is_separate_and_event_is_existence_proof_only(self):
        self.store.record_observation(self.observation(
            chain="IRON",
            asset="IRON",
            txid="tx-iron-limited",
            amountAtomic=500000000,
            precision=8,
            verification="limited",
        ))
        snapshot = self.service([self.config("IRON")]).get_snapshot()
        asset = self.asset(snapshot, "IRON")
        self.assertEqual(asset["confirmedAtomic"], "0")
        self.assertEqual(asset["limitedTotalAtomic"], "500000000")
        self.assertEqual(asset["limitedTotal"], "5")
        self.assertEqual(asset["limited"], "5")
        self.assertEqual(asset["status"], "partial")
        self.assertIsNone(asset["reference"]["usdt"])
        event = next(item for item in snapshot["events"] if item.get("txid") == "tx-iron-limited")
        self.assertEqual(set(event), {"chain", "txid", "status", "explorerUrl"})

    def test_today_uses_returned_timezone_boundaries(self):
        tz = datetime.timezone(datetime.timedelta(hours=8))
        inside = int(datetime.datetime(2026, 1, 1, 0, 30, tzinfo=tz).timestamp())
        outside = int(datetime.datetime(2025, 12, 31, 23, 30, tzinfo=tz).timestamp())
        self.store.record_observation(self.observation(txid="inside", blockTime=inside))
        self.store.record_observation(self.observation(txid="outside", blockTime=outside, amountAtomic=50))

        snapshot = self.service(timezone="+08:00").get_snapshot()
        asset = self.asset(snapshot, "KAS")
        self.assertEqual(snapshot["timezone"], "UTC+08:00")
        self.assertEqual(asset["todayAtomic"], "100")
        self.assertTrue(snapshot["todayStartAt"].endswith("+08:00"))
        self.assertTrue(snapshot["todayEndAt"].endswith("+08:00"))

    def test_masked_address_comes_from_config_not_observation(self):
        config = self.config()
        self.store.record_observation(self.observation(address="raw-address-must-not-be-used"))
        snapshot = self.service([config]).get_snapshot()
        event = snapshot["events"][0]
        self.assertNotEqual(event["address"], config["address"])
        self.assertNotIn("raw-address-must-not-be-used", json.dumps(snapshot))
        self.assertNotIn(config["address"], json.dumps(snapshot))
        self.assertIn("...", event["address"])

        full_snapshot = self.service([self.config(disclosure="full")]).get_snapshot()
        self.assertEqual(full_snapshot["events"][0]["address"], config["address"])


class CommissionIntegrationTests(PayoutTestCase):
    def setUp(self):
        super().setUp()
        self.commission = CommissionStore(
            os.path.join(self.temp_dir.name, "commission.db")
        )

    def test_refresh_settles_final_pool_and_reverses_reorg(self):
        adapter = FakeFullAdapter({
            "observations": [self.observation(amountAtomic=100)],
            "quotes": [],
        })
        relationship = {
            "producerUid": "sv_miner",
            "ancestors": [
                {"uid": "sv_l1", "role": "user", "wallet": "kas-l1"},
                {"uid": "sv_l2", "role": "user", "wallet": "kas-l2"},
            ],
        }
        service = self.service(
            adapters={"kas-fixture": adapter},
            commission_store=self.commission,
            commission_resolver=lambda event: relationship,
        )
        service.refresh()
        event_id = self.store.list_events()[0]["eventId"]
        entries = self.commission.list_entries(event_id)
        self.assertEqual([5, 2, 93], [item["amountAtomic"] for item in entries])
        self.assertTrue(all(item["paymentStatus"] != "paid" for item in entries))

        adapter.result = {
            "observations": [self.observation(
                amountAtomic=100,
                observedAt=101,
                confirmations=0,
                finality="reorg",
                status="reorg",
            )],
            "quotes": [],
        }
        service.refresh()
        entries = self.commission.list_entries(event_id)
        self.assertEqual(6, len(entries))
        self.assertEqual(0, sum(item["amountAtomic"] for item in entries))
        self.assertEqual(3, sum(item["entryKind"] == "reversal" for item in entries))

    def test_refresh_skips_ineligible_and_unmapped_events(self):
        adapter = FakeFullAdapter({
            "observations": [
                self.observation(txid="tx-pending", status="pending", finality="pending"),
                self.observation(txid="tx-pro", category="pro"),
                self.observation(txid="tx-unmapped"),
            ],
            "quotes": [],
        })
        resolved = []

        def resolver(event):
            resolved.append(event["txid"])
            return None

        service = self.service(
            adapters={"kas-fixture": adapter},
            commission_store=self.commission,
            commission_resolver=resolver,
        )
        service.refresh()
        self.assertEqual(["tx-unmapped"], resolved)
        for event in self.store.list_events():
            self.assertEqual([], self.commission.list_entries(event["eventId"]))


class ServiceTests(PayoutTestCase):
    def test_no_environment_configuration_is_unconfigured_without_demo_income(self):
        snapshot = self.service(configs=[]).get_snapshot()
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["events"], [])
        self.assertEqual({item["chain"] for item in snapshot["assets"]}, {"KAS", "PRL", "QUAN", "IRON"})
        for asset in snapshot["assets"]:
            self.assertEqual(asset["status"], "unconfigured")
            self.assertEqual(asset["confirmedAtomic"], "0")
            self.assertEqual(asset["pendingAtomic"], "0")
            self.assertEqual(asset["limitedTotalAtomic"], "0")
        self.assertTrue(all(item["code"] == "chain_unconfigured" for item in snapshot["messages"]))

    def test_environment_is_the_only_address_configuration_source(self):
        self.assertEqual(load_chain_configs({}), [])
        raw = json.dumps([self.config()])
        configs = load_chain_configs({"STONEVAST_PAYOUT_CHAINS": raw})
        self.assertEqual(configs[0]["address"], self.config()["address"])
        with self.assertRaises(ValueError):
            load_chain_configs({"STONEVAST_PAYOUT_CHAINS": json.dumps([self.config(chain="DOGE")])})
        with self.assertRaises(ValueError):
            load_chain_configs({"STONEVAST_PAYOUT_CHAINS": json.dumps([self.config(disclosure="publish-everything")])})

    def test_unverified_adapter_cannot_ingest_full_total(self):
        adapter = UnverifiedAdapter({"observations": [self.observation()], "quotes": []})
        service = self.service(adapters={"kas-fixture": adapter})
        service.refresh()
        snapshot = service.get_snapshot()
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(self.asset(snapshot, "KAS")["confirmedAtomic"], "0")
        self.assertIn(snapshot["status"], ("partial", "error"))
        self.assertTrue(any(item["code"] == "adapter_unverified" for item in snapshot["messages"]))

    def test_upstream_failure_is_isolated_and_last_known_good_is_stale(self):
        kas = FakeFullAdapter({
            "observations": [self.observation()],
            "quotes": [self.quote(), self.quote(
                quote_id="quote-cny", asset="USDT", currency="CNY", pair="USDT/CNY",
                path=["USDT/CNY"], rate="7.0",
            )],
        })
        quan_observation = self.observation(chain="QUAN", asset="QUAN", txid="tx-quan-1", amountAtomic=200)
        quan = FakeFullAdapter({"observations": [quan_observation], "quotes": []})
        adapters = {"kas-fixture": kas, "quan-fixture": quan}
        service = self.service([self.config("KAS"), self.config("QUAN")], adapters)
        service.refresh()
        self.assertEqual(self.asset(service.get_snapshot(), "KAS")["confirmedAtomic"], "100")

        self.now = 1050
        kas.error = RuntimeError("secret-upstream-detail-must-not-leak")
        quan.result = {
            "observations": [self.observation(
                chain="QUAN", asset="QUAN", txid="tx-quan-2", amountAtomic=300, observedAt=1050,
            )],
            "quotes": [],
        }
        service.refresh()
        snapshot = service.get_snapshot()
        self.assertEqual(snapshot["status"], "stale")
        self.assertTrue(snapshot["stale"])
        self.assertEqual(self.asset(snapshot, "KAS")["confirmedAtomic"], "100")
        self.assertEqual(self.asset(snapshot, "QUAN")["confirmedAtomic"], "300")
        self.assertEqual(quan.calls, 2)
        self.assertGreaterEqual(self.asset(snapshot, "KAS")["dataAgeSeconds"], 50)
        self.assertNotIn("secret-upstream-detail", json.dumps(snapshot))

    def test_initial_upstream_failure_returns_error_without_last_known_good(self):
        adapter = FakeFullAdapter()
        adapter.error = RuntimeError("offline")
        service = self.service(adapters={"kas-fixture": adapter})
        service.refresh()
        snapshot = service.get_snapshot()
        self.assertEqual(snapshot["status"], "error")
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(self.asset(snapshot, "KAS")["status"], "error")

    def test_http_has_only_public_get_routes_and_restricted_cors(self):
        server = create_http_server(self.service(configs=[]), ("127.0.0.1", 0))
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        host, port = server.server_address
        try:
            connection = http.client.HTTPConnection(host, port, timeout=3)
            connection.request("GET", "/api/public/payouts", headers={"Origin": "https://haolinsong32-lang.github.io"})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "https://haolinsong32-lang.github.io")
            self.assertEqual(response.getheader("Vary"), "Origin")
            self.assertIsNone(response.getheader("Access-Control-Allow-Credentials"))
            self.assertEqual(payload["refreshSeconds"], 600)

            connection.request("GET", "/api/public/payouts/health")
            response = connection.getresponse()
            health = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertTrue(health["ok"])
            self.assertNotIn("database", health)

            for path in ("/health", "/api/public/other"):
                connection.request("GET", path)
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 404)

            connection.request("POST", "/api/public/payouts", body="{}")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 405)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    unittest.main()
