#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import json
import os
import re
import sqlite3
import threading


RULE_VERSION = "infinite-halving-v1"
_DIGITS = re.compile(r"^[0-9]+$")


def _integer(value, name, minimum=0):
    if isinstance(value, bool):
        raise ValueError("%s must be an integer" % name)
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and _DIGITS.match(value):
        result = int(value)
    else:
        raise ValueError("%s must be an integer" % name)
    if result < minimum:
        raise ValueError("%s is out of range" % name)
    return result


def _required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s is required" % name)
    return value.strip()


def tier_rate(tier, genesis=False):
    tier = _integer(tier, "tier", minimum=1)
    if tier == 1:
        return (3, 10) if genesis else (1, 20)
    if tier == 2:
        return (1, 50)
    return (1, 100 * 2 ** (tier - 3))


def split_net_output(amount_atomic, ancestors, producer_uid):
    amount = _integer(amount_atomic, "amountAtomic")
    producer_uid = _required_text(producer_uid, "producerUid")
    if not isinstance(ancestors, (list, tuple)):
        raise ValueError("ancestors must be a list")

    allocations = []
    allocated = 0
    seen = {producer_uid}
    for tier, ancestor in enumerate(ancestors, 1):
        if not isinstance(ancestor, dict):
            raise ValueError("ancestor must be an object")
        uid = _required_text(ancestor.get("uid"), "ancestor.uid")
        if uid in seen:
            raise ValueError("duplicate ancestor or producer relationship")
        seen.add(uid)
        wallet = ancestor.get("wallet", "")
        if not isinstance(wallet, str):
            raise ValueError("ancestor.wallet must be a string")
        wallet = wallet.strip()
        numerator, denominator = tier_rate(
            tier, genesis=tier == 1 and ancestor.get("role") == "genesis"
        )
        share = amount * numerator // denominator
        allocated += share
        allocations.append(
            {
                "tier": tier,
                "beneficiaryUid": uid,
                "wallet": wallet,
                "numerator": numerator,
                "denominator": denominator,
                "amountAtomic": share,
                "entryKind": "commission",
                "paymentStatus": "accrued_not_paid" if wallet else "address_required",
            }
        )

    return {
        "ruleVersion": RULE_VERSION,
        "netOutputAtomic": amount,
        "allocatedAtomic": allocated,
        "producerRetainedAtomic": amount - allocated,
        "allocations": allocations,
    }


class CommissionStore(object):
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._lock:
            connection = self._connect()
            try:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS commission_entries (
                        entry_id TEXT PRIMARY KEY,
                        rule_version TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        beneficiary_uid TEXT NOT NULL,
                        tier INTEGER NOT NULL,
                        entry_kind TEXT NOT NULL,
                        amount_atomic TEXT NOT NULL,
                        numerator TEXT,
                        denominator TEXT,
                        wallet TEXT NOT NULL,
                        payment_status TEXT NOT NULL,
                        reversal_of TEXT,
                        observed_at INTEGER NOT NULL,
                        UNIQUE(rule_version, event_id, beneficiary_uid, tier, entry_kind)
                    );
                    CREATE INDEX IF NOT EXISTS commission_entries_event_idx
                        ON commission_entries(event_id);
                    """
                )
                connection.commit()
            finally:
                connection.close()

    @staticmethod
    def _entry_id(rule_version, event_id, uid, tier, entry_kind):
        key = json.dumps(
            [rule_version, event_id, uid, tier, entry_kind],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(key).hexdigest()

    @classmethod
    def _insert_entry(cls, connection, event_id, item, observed_at, reversal_of=None):
        entry_id = cls._entry_id(
            RULE_VERSION, event_id, item["beneficiaryUid"], item["tier"], item["entryKind"]
        )
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO commission_entries (
                entry_id, rule_version, event_id, beneficiary_uid, tier,
                entry_kind, amount_atomic, numerator, denominator, wallet,
                payment_status, reversal_of, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                RULE_VERSION,
                event_id,
                item["beneficiaryUid"],
                item["tier"],
                item["entryKind"],
                str(item["amountAtomic"]),
                str(item.get("numerator", "")),
                str(item.get("denominator", "")),
                item.get("wallet", ""),
                item["paymentStatus"],
                reversal_of,
                observed_at,
            ),
        )
        return cursor.rowcount == 1

    @staticmethod
    def _validate_event(event):
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        event_id = _required_text(event.get("eventId"), "eventId")
        if event.get("status") != "finality":
            raise ValueError("only finality events can be settled")
        if event.get("category") != "pool":
            raise ValueError("only pool output can be settled")
        if event.get("verification") != "full":
            raise ValueError("only fully verified events can be settled")
        if event.get("internal") is not False or event.get("change") is not False:
            raise ValueError("internal or change events cannot be settled")
        if _integer(event.get("amountAtomic"), "amountAtomic") <= 0:
            raise ValueError("amountAtomic must be positive")
        return event_id

    def settle_event(self, event, ancestors, producer_uid, observed_at):
        event_id = self._validate_event(event)
        observed_at = _integer(observed_at, "observedAt")
        split = split_net_output(event["amountAtomic"], ancestors, producer_uid)
        entries = list(split["allocations"])
        entries.append(
            {
                "tier": 0,
                "beneficiaryUid": producer_uid,
                "wallet": "",
                "numerator": split["producerRetainedAtomic"],
                "denominator": split["netOutputAtomic"],
                "amountAtomic": split["producerRetainedAtomic"],
                "entryKind": "retention",
                "paymentStatus": "accrued_not_paid",
            }
        )

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                created = False
                for item in entries:
                    created = self._insert_entry(
                        connection, event_id, item, observed_at
                    ) or created
                connection.commit()
                return {
                    "created": created,
                    "ruleVersion": RULE_VERSION,
                    "entryCount": len(entries) if created else 0,
                }
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def reverse_event(self, event_id, observed_at):
        event_id = _required_text(event_id, "eventId")
        observed_at = _integer(observed_at, "observedAt")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                originals = connection.execute(
                    """
                    SELECT * FROM commission_entries
                    WHERE event_id = ? AND entry_kind != 'reversal'
                    ORDER BY rowid
                    """,
                    (event_id,),
                ).fetchall()
                if not originals:
                    connection.commit()
                    return {"created": False, "entryCount": 0}
                existing = connection.execute(
                    """
                    SELECT 1 FROM commission_entries
                    WHERE event_id = ? AND entry_kind = 'reversal' LIMIT 1
                    """,
                    (event_id,),
                ).fetchone()
                if existing:
                    connection.commit()
                    return {"created": False, "entryCount": 0}

                created = 0
                for row in originals:
                    item = {
                        "tier": row["tier"],
                        "beneficiaryUid": row["beneficiary_uid"],
                        "wallet": row["wallet"],
                        "numerator": row["numerator"],
                        "denominator": row["denominator"],
                        "amountAtomic": -int(row["amount_atomic"]),
                        "entryKind": "reversal",
                        "paymentStatus": row["payment_status"],
                    }
                    created += int(
                        self._insert_entry(
                            connection,
                            event_id,
                            item,
                            observed_at,
                            reversal_of=row["entry_id"],
                        )
                    )
                connection.commit()
                return {"created": created > 0, "entryCount": created}
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def list_entries(self, event_id):
        event_id = _required_text(event_id, "eventId")
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT * FROM commission_entries WHERE event_id = ? ORDER BY rowid",
                    (event_id,),
                ).fetchall()
            finally:
                connection.close()
        return [
            {
                "entryId": row["entry_id"],
                "ruleVersion": row["rule_version"],
                "eventId": row["event_id"],
                "beneficiaryUid": row["beneficiary_uid"],
                "tier": row["tier"],
                "entryKind": row["entry_kind"],
                "amountAtomic": int(row["amount_atomic"]),
                "numerator": int(row["numerator"]) if row["numerator"] else None,
                "denominator": int(row["denominator"]) if row["denominator"] else None,
                "wallet": row["wallet"],
                "paymentStatus": row["payment_status"],
                "reversalOf": row["reversal_of"],
                "observedAt": row["observed_at"],
            }
            for row in rows
        ]
