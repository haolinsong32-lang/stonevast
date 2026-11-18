#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import decimal
import json
import os
import re
import sqlite3
import threading


DEFAULT_DB_PATH = "/var/lib/stonevast/payouts/payouts.db"
_EVENT_STATUSES = ("pending", "finality", "reorg", "reverted")
_CATEGORIES = ("pool", "other", "pro", "self", "unknown")
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


def format_atomic(value, precision):
    amount = _integer(value, "amountAtomic")
    precision = _integer(precision, "precision")
    if precision == 0:
        return str(amount)
    digits = str(amount).rjust(precision + 1, "0")
    whole = digits[:-precision]
    fraction = digits[-precision:].rstrip("0")
    return whole + ("." + fraction if fraction else "")


def _decimal_text(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _json_value(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PayoutStore(object):
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = path
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        with self._lock:
            connection = self._connect()
            try:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        chain TEXT NOT NULL,
                        asset TEXT NOT NULL,
                        txid TEXT NOT NULL,
                        output_index TEXT,
                        log_index TEXT,
                        amount_atomic TEXT NOT NULL,
                        precision INTEGER NOT NULL,
                        block_height INTEGER,
                        block_time INTEGER,
                        first_observed_at INTEGER NOT NULL,
                        last_observed_at INTEGER NOT NULL,
                        state_changed_at INTEGER NOT NULL,
                        confirmations INTEGER NOT NULL,
                        finality TEXT NOT NULL,
                        status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        category TEXT NOT NULL,
                        verification TEXT NOT NULL,
                        quote_id TEXT,
                        internal INTEGER NOT NULL DEFAULT 0,
                        change INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS events_chain_idx
                        ON events(chain, block_time);

                    CREATE TABLE IF NOT EXISTS evidence (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL REFERENCES events(event_id),
                        source TEXT NOT NULL,
                        evidence_key TEXT NOT NULL,
                        observed_at INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        UNIQUE(event_id, source, evidence_key)
                    );

                    CREATE TABLE IF NOT EXISTS observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL REFERENCES events(event_id),
                        observed_at INTEGER NOT NULL,
                        payload TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS observations_event_idx
                        ON observations(event_id, observed_at);

                    CREATE TABLE IF NOT EXISTS cursors (
                        chain TEXT NOT NULL,
                        source TEXT NOT NULL,
                        cursor TEXT NOT NULL,
                        updated_at INTEGER NOT NULL,
                        PRIMARY KEY(chain, source)
                    );

                    CREATE TABLE IF NOT EXISTS quotes (
                        quote_id TEXT PRIMARY KEY,
                        asset TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        pair TEXT NOT NULL,
                        path TEXT NOT NULL,
                        rate TEXT NOT NULL,
                        source TEXT NOT NULL,
                        quote_time INTEGER NOT NULL,
                        observed_at INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS chain_state (
                        chain TEXT PRIMARY KEY,
                        active_event_ids TEXT,
                        last_success_at INTEGER,
                        last_error TEXT
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

    @staticmethod
    def _normalize_observation(observation):
        if not isinstance(observation, dict):
            raise ValueError("observation must be an object")
        chain = _required_text(observation.get("chain"), "chain").upper()
        asset = _required_text(observation.get("asset"), "asset").upper()
        txid = _required_text(observation.get("txid"), "txid")
        output_index = observation.get("outputIndex")
        log_index = observation.get("logIndex")
        if output_index is None and log_index is None:
            raise ValueError("outputIndex or logIndex is required")
        if output_index is not None:
            output_index = str(_integer(output_index, "outputIndex"))
        if log_index is not None:
            log_index = str(_integer(log_index, "logIndex"))
        event_key = output_index if output_index is not None else log_index
        event_id = "%s:%s:%s" % (chain, txid, event_key)
        status = _required_text(observation.get("status"), "status")
        category = _required_text(observation.get("category"), "category")
        if status not in _EVENT_STATUSES:
            raise ValueError("unsupported event status")
        if category not in _CATEGORIES:
            raise ValueError("unsupported event category")
        evidence = observation.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise ValueError("evidence must be an object")
        normalized = {
            "eventId": event_id,
            "chain": chain,
            "asset": asset,
            "txid": txid,
            "outputIndex": output_index,
            "logIndex": log_index,
            "amountAtomic": _integer(observation.get("amountAtomic"), "amountAtomic"),
            "precision": _integer(observation.get("precision"), "precision"),
            "blockHeight": observation.get("blockHeight"),
            "blockTime": observation.get("blockTime"),
            "observedAt": _integer(observation.get("observedAt"), "observedAt"),
            "confirmations": _integer(observation.get("confirmations", 0), "confirmations"),
            "finality": _required_text(observation.get("finality"), "finality"),
            "status": status,
            "source": _required_text(observation.get("source"), "source"),
            "category": category,
            "verification": _required_text(observation.get("verification"), "verification"),
            "quoteId": observation.get("quoteId"),
            "internal": bool(observation.get("internal", False)),
            "change": bool(observation.get("change", False)),
            "evidence": evidence,
            "evidenceKey": _required_text(
                evidence.get("key", observation.get("source")), "evidence.key"
            ),
            "cursor": observation.get("cursor"),
        }
        if normalized["blockHeight"] is not None:
            normalized["blockHeight"] = _integer(normalized["blockHeight"], "blockHeight")
        if normalized["blockTime"] is not None:
            normalized["blockTime"] = _integer(normalized["blockTime"], "blockTime")
        return normalized

    def record_observation(self, observation):
        item = self._normalize_observation(observation)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM events WHERE event_id = ?", (item["eventId"],)
                ).fetchone()
                if row is not None:
                    if int(row["amount_atomic"]) != item["amountAtomic"]:
                        raise ValueError("conflicting atomic amount for event")
                    if row["asset"] != item["asset"] or row["precision"] != item["precision"]:
                        raise ValueError("conflicting asset or precision for event")

                if row is None:
                    connection.execute(
                        """INSERT INTO events (
                            event_id, chain, asset, txid, output_index, log_index,
                            amount_atomic, precision, block_height, block_time,
                            first_observed_at, last_observed_at, state_changed_at,
                            confirmations, finality, status, source, category,
                            verification, quote_id, internal, change
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item["eventId"], item["chain"], item["asset"], item["txid"],
                            item["outputIndex"], item["logIndex"], str(item["amountAtomic"]),
                            item["precision"], item["blockHeight"], item["blockTime"],
                            item["observedAt"], item["observedAt"], item["observedAt"],
                            item["confirmations"], item["finality"], item["status"],
                            item["source"], item["category"], item["verification"],
                            item["quoteId"], int(item["internal"]), int(item["change"]),
                        ),
                    )
                else:
                    first_observed = min(row["first_observed_at"], item["observedAt"])
                    if item["observedAt"] > row["last_observed_at"]:
                        state_changed = row["state_changed_at"]
                        if item["status"] != row["status"]:
                            state_changed = item["observedAt"]
                        connection.execute(
                            """UPDATE events SET
                                block_height = ?, block_time = ?, first_observed_at = ?,
                                last_observed_at = ?, state_changed_at = ?, confirmations = ?,
                                finality = ?, status = ?, source = ?, category = ?,
                                verification = ?, quote_id = ?, internal = ?, change = ?
                               WHERE event_id = ?""",
                            (
                                item["blockHeight"], item["blockTime"], first_observed,
                                item["observedAt"], state_changed, item["confirmations"],
                                item["finality"], item["status"], item["source"],
                                item["category"], item["verification"], item["quoteId"],
                                int(item["internal"]), int(item["change"]), item["eventId"],
                            ),
                        )
                    elif first_observed != row["first_observed_at"]:
                        connection.execute(
                            "UPDATE events SET first_observed_at = ? WHERE event_id = ?",
                            (first_observed, item["eventId"]),
                        )

                connection.execute(
                    "INSERT INTO observations (event_id, observed_at, payload) VALUES (?, ?, ?)",
                    (item["eventId"], item["observedAt"], _json_value(observation)),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO evidence
                       (event_id, source, evidence_key, observed_at, payload)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        item["eventId"], item["source"], item["evidenceKey"],
                        item["observedAt"], _json_value(item["evidence"]),
                    ),
                )
                if item["cursor"] is not None:
                    connection.execute(
                        "DELETE FROM cursors WHERE chain = ? AND source = ?",
                        (item["chain"], item["source"]),
                    )
                    connection.execute(
                        "INSERT INTO cursors (chain, source, cursor, updated_at) VALUES (?, ?, ?, ?)",
                        (
                            item["chain"], item["source"], str(item["cursor"]),
                            item["observedAt"],
                        ),
                    )
                connection.commit()
                return item["eventId"]
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _event_from_row(row):
        return {
            "eventId": row["event_id"],
            "chain": row["chain"],
            "asset": row["asset"],
            "txid": row["txid"],
            "outputIndex": row["output_index"],
            "logIndex": row["log_index"],
            "amountAtomic": int(row["amount_atomic"]),
            "precision": row["precision"],
            "blockHeight": row["block_height"],
            "blockTime": row["block_time"],
            "firstObservedAt": row["first_observed_at"],
            "lastObservedAt": row["last_observed_at"],
            "stateChangedAt": row["state_changed_at"],
            "confirmations": row["confirmations"],
            "finality": row["finality"],
            "status": row["status"],
            "source": row["source"],
            "category": row["category"],
            "verification": row["verification"],
            "quoteId": row["quote_id"],
            "internal": bool(row["internal"]),
            "change": bool(row["change"]),
        }

    def list_events(self):
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT * FROM events ORDER BY block_time, event_id"
                ).fetchall()
                return [self._event_from_row(row) for row in rows]
            finally:
                connection.close()

    def get_event(self, event_id):
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT * FROM events WHERE event_id = ?", (event_id,)
                ).fetchone()
                return self._event_from_row(row) if row is not None else None
            finally:
                connection.close()

    def list_evidence(self, event_id):
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT * FROM evidence WHERE event_id = ? ORDER BY id", (event_id,)
                ).fetchall()
                result = []
                for row in rows:
                    value = json.loads(row["payload"])
                    value.update({
                        "key": row["evidence_key"],
                        "source": row["source"],
                        "observedAt": row["observed_at"],
                    })
                    result.append(value)
                return result
            finally:
                connection.close()

    def list_observations(self, event_id):
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT * FROM observations WHERE event_id = ? ORDER BY id", (event_id,)
                ).fetchall()
                return [{
                    "id": row["id"],
                    "eventId": row["event_id"],
                    "observedAt": row["observed_at"],
                    "observation": json.loads(row["payload"]),
                } for row in rows]
            finally:
                connection.close()

    def get_cursor(self, chain, source):
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT cursor FROM cursors WHERE chain = ? AND source = ?",
                    (chain.upper(), source),
                ).fetchone()
                return row["cursor"] if row is not None else None
            finally:
                connection.close()

    def record_quote(self, quote):
        if not isinstance(quote, dict):
            raise ValueError("quote must be an object")
        quote_id = _required_text(quote.get("quoteId"), "quoteId")
        asset = _required_text(quote.get("asset"), "asset").upper()
        currency = _required_text(quote.get("currency"), "currency").upper()
        pair = _required_text(quote.get("pair"), "pair")
        source = _required_text(quote.get("source"), "source")
        path = quote.get("path")
        if not isinstance(path, list) or not path or not all(isinstance(item, str) for item in path):
            raise ValueError("quote path must be a non-empty string array")
        rate_value = quote.get("rate")
        if isinstance(rate_value, (float, bool)):
            raise ValueError("quote rate must be a decimal string or integer")
        try:
            rate = decimal.Decimal(str(rate_value))
        except decimal.InvalidOperation:
            raise ValueError("invalid quote rate")
        if not rate.is_finite() or rate <= 0:
            raise ValueError("quote rate must be positive and finite")
        quote_time = _integer(quote.get("quoteTime"), "quoteTime")
        observed_at = _integer(quote.get("observedAt"), "observedAt")
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)
                ).fetchone()
                if row is not None and (
                    row["asset"] != asset or row["currency"] != currency or row["pair"] != pair
                ):
                    raise ValueError("conflicting quote identity")
                if row is None or observed_at >= row["observed_at"]:
                    connection.execute("DELETE FROM quotes WHERE quote_id = ?", (quote_id,))
                    connection.execute(
                        """INSERT INTO quotes (
                            quote_id, asset, currency, pair, path, rate, source,
                            quote_time, observed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            quote_id, asset, currency, pair, _json_value(path),
                            _decimal_text(rate), source, quote_time, observed_at,
                        ),
                    )
                connection.commit()
                return quote_id
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def list_quotes(self):
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT * FROM quotes ORDER BY quote_time, quote_id"
                ).fetchall()
                return [{
                    "quoteId": row["quote_id"],
                    "asset": row["asset"],
                    "currency": row["currency"],
                    "pair": row["pair"],
                    "path": json.loads(row["path"]),
                    "rate": row["rate"],
                    "source": row["source"],
                    "quoteTime": row["quote_time"],
                    "observedAt": row["observed_at"],
                } for row in rows]
            finally:
                connection.close()

    def get_chain_state(self, chain):
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT * FROM chain_state WHERE chain = ?", (chain.upper(),)
                ).fetchone()
                if row is None:
                    return None
                return {
                    "activeEventIds": (
                        json.loads(row["active_event_ids"])
                        if row["active_event_ids"] is not None else None
                    ),
                    "lastSuccessAt": row["last_success_at"],
                    "lastError": row["last_error"],
                }
            finally:
                connection.close()

    def record_chain_success(self, chain, event_ids, observed_at):
        self._write_chain_state(chain.upper(), sorted(set(event_ids)), observed_at, None)

    def record_chain_error(self, chain, code):
        previous = self.get_chain_state(chain)
        self._write_chain_state(
            chain.upper(),
            previous["activeEventIds"] if previous else None,
            previous["lastSuccessAt"] if previous else None,
            code,
        )

    def _write_chain_state(self, chain, active_event_ids, last_success_at, last_error):
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("DELETE FROM chain_state WHERE chain = ?", (chain,))
                connection.execute(
                    """INSERT INTO chain_state
                       (chain, active_event_ids, last_success_at, last_error)
                       VALUES (?, ?, ?, ?)""",
                    (
                        chain,
                        _json_value(active_event_ids) if active_event_ids is not None else None,
                        last_success_at,
                        last_error,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
