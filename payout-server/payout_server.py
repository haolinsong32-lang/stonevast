#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import decimal
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

from payout_adapters import build_default_adapters
from payout_store import DEFAULT_DB_PATH, PayoutStore, format_atomic


BIND = ("127.0.0.1", 8794)
REFRESH_SECONDS = 600
STALE_AFTER_SECONDS = 1800
QUOTE_STALE_SECONDS = 3600
SUPPORTED_CHAINS = ("KAS", "PRL", "QUAN", "IRON")
DEFAULT_PRECISION = {"KAS": 8, "PRL": 8, "QUAN": 8, "IRON": 8}
PAGES_ORIGIN = "https://haolinsong32-lang.github.io"
_TIMEZONE_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def _iso_utc(timestamp):
    return datetime.datetime.fromtimestamp(
        int(timestamp), datetime.timezone.utc
    ).isoformat()


def _decimal_text(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _masked_address(address):
    if len(address) <= 12:
        return address[:2] + "..." + address[-2:]
    return address[:6] + "..." + address[-4:]


def _timezone(value):
    if value == "UTC":
        return datetime.timezone.utc, "UTC"
    match = _TIMEZONE_RE.match(value)
    if not match:
        raise ValueError("timezone must be UTC or +HH:MM/-HH:MM")
    hours = int(match.group(2))
    minutes = int(match.group(3))
    if hours > 23 or minutes > 59:
        raise ValueError("invalid timezone offset")
    offset = datetime.timedelta(hours=hours, minutes=minutes)
    if match.group(1) == "-":
        offset = -offset
    sign = "+" if match.group(1) == "+" else "-"
    return datetime.timezone(offset), "UTC%s%02d:%02d" % (sign, hours, minutes)


def load_chain_configs(environ):
    raw = environ.get("STONEVAST_PAYOUT_CHAINS", "").strip()
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("STONEVAST_PAYOUT_CHAINS must be valid JSON")
    if not isinstance(values, list):
        raise ValueError("STONEVAST_PAYOUT_CHAINS must be an array")

    configs = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("each chain config must be an object")
        chain = str(value.get("chain", "")).upper()
        if chain not in SUPPORTED_CHAINS:
            raise ValueError("unsupported payout chain")
        if chain in seen:
            raise ValueError("duplicate payout chain")
        seen.add(chain)
        asset = str(value.get("asset", chain)).upper()
        if asset != chain:
            raise ValueError("asset must match its canonical chain")
        address = value.get("address")
        network = value.get("network")
        adapter = value.get("adapter")
        disclosure = value.get("disclosure", "masked")
        if not isinstance(address, str) or not address.strip():
            raise ValueError("a public address is required")
        if not isinstance(network, str) or not network.strip():
            raise ValueError("a public network is required")
        if not isinstance(adapter, str) or not adapter.strip():
            raise ValueError("an adapter name is required")
        if disclosure not in ("masked", "full"):
            raise ValueError("disclosure must be masked or full")
        config = {
            "chain": chain,
            "asset": asset,
            "network": network.strip(),
            "address": address.strip(),
            "disclosure": disclosure,
            "adapter": adapter.strip(),
        }
        if "precision" in value:
            precision = value["precision"]
            if isinstance(precision, bool) or not isinstance(precision, int) or precision < 0:
                raise ValueError("precision must be a non-negative integer")
            config["precision"] = precision
        configs.append(config)
    return configs


class PayoutService(object):
    def __init__(
        self, store, configs, adapters, now=None, timezone="UTC",
        commission_store=None, commission_resolver=None,
    ):
        self.store = store
        self.configs = list(configs)
        self.adapters = dict(adapters)
        self.now = now or (lambda: int(time.time()))
        self.timezone, self.timezone_label = _timezone(timezone)
        self.commission_store = commission_store
        self.commission_resolver = commission_resolver
        self._refresh_lock = threading.Lock()

    def refresh(self):
        with self._refresh_lock:
            for config in self.configs:
                chain = config["chain"]
                adapter = self.adapters.get(config["adapter"])
                if adapter is None:
                    self.store.record_chain_error(chain, "adapter_unsupported")
                    continue
                adapter_level = getattr(adapter, "verification_level", "unverified")
                if adapter_level not in ("full", "limited") or (
                    adapter_level == "limited" and chain != "IRON"
                ):
                    self.store.record_chain_error(chain, "adapter_unverified")
                    continue
                try:
                    result = adapter.collect(dict(config))
                    if not isinstance(result, dict):
                        raise ValueError("adapter result must be an object")
                    observations = result.get("observations", [])
                    quotes = result.get("quotes", [])
                    if not isinstance(observations, list) or not isinstance(quotes, list):
                        raise ValueError("adapter collections must be arrays")
                    for observation in observations:
                        if not isinstance(observation, dict):
                            raise ValueError("observation must be an object")
                        if str(observation.get("chain", "")).upper() != chain:
                            raise ValueError("cross-chain observation rejected")
                        if str(observation.get("asset", "")).upper() != config["asset"]:
                            raise ValueError("cross-asset observation rejected")
                        verification = observation.get("verification")
                        if verification not in ("full", "limited"):
                            raise ValueError("unverified observation rejected")
                        if verification == "full" and adapter_level != "full":
                            raise ValueError("adapter cannot fully verify observation")
                        if verification == "limited" and chain != "IRON":
                            raise ValueError("limited verification is IRON-only")
                    event_ids = []
                    for observation in observations:
                        event_id = self.store.record_observation(observation)
                        event_ids.append(event_id)
                        self._sync_commission(event_id)
                    for quote in quotes:
                        self.store.record_quote(quote)
                    self.store.record_chain_success(chain, event_ids, int(self.now()))
                except Exception as error:
                    self.store.record_chain_error(chain, "upstream_failed")
                    sys.stderr.write(
                        "payout refresh failed chain=%s error=%s\n"
                        % (chain, type(error).__name__)
                    )

    def _sync_commission(self, event_id):
        if self.commission_store is None or self.commission_resolver is None:
            return
        event = self.store.get_event(event_id)
        if event["status"] in ("reorg", "reverted"):
            self.commission_store.reverse_event(
                event_id, observed_at=event["lastObservedAt"]
            )
            return
        if (
            event["status"] != "finality"
            or event["verification"] != "full"
            or not self._eligible(event)
        ):
            return
        relationship = self.commission_resolver(event)
        if relationship is None:
            return
        self.commission_store.settle_event(
            event,
            relationship["ancestors"],
            producer_uid=relationship["producerUid"],
            observed_at=event["lastObservedAt"],
        )

    def _public_event(self, event, config, evidence):
        if event["verification"] == "limited":
            explorer_url = None
            for item in evidence:
                if item.get("url"):
                    explorer_url = item["url"]
                    break
            return {
                "chain": event["chain"],
                "txid": event["txid"],
                "status": event["status"],
                "explorerUrl": explorer_url,
            }
        address = config["address"]
        if config["disclosure"] == "masked":
            address = _masked_address(address)
        public_evidence = [{
            "key": item.get("key"),
            "source": item.get("source"),
            "url": item.get("url"),
            "observedAt": item.get("observedAt"),
        } for item in evidence]
        return {
            "eventId": event["eventId"],
            "chain": event["chain"],
            "asset": event["asset"],
            "txid": event["txid"],
            "outputIndex": event["outputIndex"],
            "logIndex": event["logIndex"],
            "address": address,
            "amountAtomic": str(event["amountAtomic"]),
            "amount": format_atomic(event["amountAtomic"], event["precision"]),
            "precision": event["precision"],
            "blockHeight": event["blockHeight"],
            "blockTime": event["blockTime"],
            "firstObservedAt": event["firstObservedAt"],
            "lastObservedAt": event["lastObservedAt"],
            "stateChangedAt": event["stateChangedAt"],
            "confirmations": event["confirmations"],
            "finality": event["finality"],
            "status": event["status"],
            "source": event["source"],
            "category": event["category"],
            "verification": event["verification"],
            "quoteId": event["quoteId"],
            "internal": event["internal"],
            "change": event["change"],
            "evidence": public_evidence,
        }

    @staticmethod
    def _eligible(event):
        return (
            event["category"] == "pool"
            and not event["internal"]
            and not event["change"]
        )

    def _reference(self, asset_name, confirmed_atomic, precision, quotes, now):
        usdt_quote = self._latest_quote(quotes, asset_name, "USDT")
        cny_quote = self._latest_quote(quotes, "USDT", "CNY")
        used = [quote for quote in (usdt_quote, cny_quote) if quote is not None]
        quote_ids = [quote["quoteId"] for quote in used]
        path = []
        sources = []
        for quote in used:
            path.extend(quote["path"])
            if quote["source"] not in sources:
                sources.append(quote["source"])
        quote_time = min([quote["quoteTime"] for quote in used]) if used else None
        stale = any(now - quote["quoteTime"] > QUOTE_STALE_SECONDS for quote in used)
        usdt = None
        cny = None
        with decimal.localcontext() as context:
            context.prec = 80
            amount = decimal.Decimal(confirmed_atomic) / (decimal.Decimal(10) ** precision)
            if usdt_quote is not None:
                usdt = _decimal_text(amount * decimal.Decimal(usdt_quote["rate"]))
            if usdt_quote is not None and cny_quote is not None:
                cny = _decimal_text(
                    amount
                    * decimal.Decimal(usdt_quote["rate"])
                    * decimal.Decimal(cny_quote["rate"])
                )
        if usdt_quote is None or cny_quote is None:
            status = "partial"
        elif stale:
            status = "stale"
        else:
            status = "ok"
        return {
            "usdt": usdt,
            "cny": cny,
            "status": status,
            "quoteIds": quote_ids,
            "path": path,
            "sources": sources,
            "quoteTime": quote_time,
        }

    @staticmethod
    def _latest_quote(quotes, asset, currency):
        candidates = [
            quote for quote in quotes
            if quote["asset"] == asset and quote["currency"] == currency
        ]
        if not candidates:
            return None
        return sorted(
            candidates, key=lambda quote: (quote["quoteTime"], quote["observedAt"], quote["quoteId"])
        )[-1]

    def get_snapshot(self):
        now = int(self.now())
        configs = dict((config["chain"], config) for config in self.configs)
        states = dict((chain, self.store.get_chain_state(chain)) for chain in SUPPORTED_CHAINS)
        stored_events = self.store.list_events()
        events = []
        for event in stored_events:
            chain = event["chain"]
            if chain not in configs:
                continue
            state = states.get(chain)
            if state is not None and state["activeEventIds"] is not None:
                if event["eventId"] not in state["activeEventIds"]:
                    continue
            events.append(event)
        quotes = self.store.list_quotes()

        latest_block_time = max(
            [now] + [event["blockTime"] for event in events if event["blockTime"] is not None]
        )
        current = datetime.datetime.fromtimestamp(latest_block_time, self.timezone)
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)
        start_timestamp = int(start.timestamp())
        end_timestamp = int(end.timestamp())

        assets = []
        messages = []
        public_events = []
        for chain in SUPPORTED_CHAINS:
            config = configs.get(chain)
            state = states.get(chain)
            if config is None:
                reference = self._reference(chain, 0, DEFAULT_PRECISION[chain], [], now)
                assets.append({
                    "chain": chain,
                    "asset": chain,
                    "network": None,
                    "status": "unconfigured",
                    "verificationLevel": "unconfigured",
                    "confirmedAtomic": "0",
                    "confirmed": "0",
                    "pendingAtomic": "0",
                    "pending": "0",
                    "limitedTotalAtomic": "0",
                    "limitedTotal": "0",
                    "limited": "0",
                    "todayAtomic": "0",
                    "today": "0",
                    "reference": reference,
                    "dataAgeSeconds": None,
                    "lastSuccessAt": None,
                    "lastObservedAt": None,
                })
                messages.append({
                    "code": "chain_unconfigured",
                    "chain": chain,
                    "message": "No authorized public address is configured.",
                })
                continue

            chain_events = [event for event in events if event["chain"] == chain]
            precision = config.get("precision")
            if precision is None:
                precision = chain_events[0]["precision"] if chain_events else DEFAULT_PRECISION[chain]
            confirmed_atomic = sum(
                event["amountAtomic"] for event in chain_events
                if self._eligible(event)
                and event["verification"] == "full"
                and event["status"] == "finality"
            )
            pending_atomic = sum(
                event["amountAtomic"] for event in chain_events
                if self._eligible(event)
                and event["verification"] == "full"
                and event["status"] == "pending"
            )
            limited_atomic = sum(
                event["amountAtomic"] for event in chain_events
                if chain == "IRON"
                and self._eligible(event)
                and event["verification"] == "limited"
                and event["status"] == "finality"
            )
            today_atomic = sum(
                event["amountAtomic"] for event in chain_events
                if self._eligible(event)
                and event["verification"] == "full"
                and event["status"] == "finality"
                and event["blockTime"] is not None
                and start_timestamp <= event["blockTime"] < end_timestamp
            )
            reference = self._reference(config["asset"], confirmed_atomic, precision, quotes, now)
            last_observed = max(
                [event["lastObservedAt"] for event in chain_events] or [None]
            )
            last_success = state["lastSuccessAt"] if state else None
            age_base = last_success if last_success is not None else last_observed
            data_age = max(0, now - age_base) if age_base is not None else None
            upstream_stale = (
                last_success is not None and now - last_success > STALE_AFTER_SECONDS
            )
            if state and state["lastError"]:
                messages.append({
                    "code": state["lastError"],
                    "chain": chain,
                    "message": "The chain collector is unavailable; no upstream detail is exposed.",
                })
            if reference["status"] == "partial":
                messages.append({
                    "code": "quote_missing",
                    "chain": chain,
                    "message": "A required USDT or CNY quote is unavailable.",
                })
            if limited_atomic:
                messages.append({
                    "code": "limited_verification",
                    "chain": chain,
                    "message": "Wallet amount and chain existence have limited verification.",
                })

            if state and state["lastError"] and last_success is None:
                asset_status = "error"
            elif (state and state["lastError"]) or upstream_stale or reference["status"] == "stale":
                asset_status = "stale"
            elif (
                state is None
                or last_success is None
                or reference["status"] == "partial"
                or limited_atomic
            ):
                asset_status = "partial"
            else:
                asset_status = "ok"
            address = config["address"]
            if config["disclosure"] == "masked":
                address = _masked_address(address)
            assets.append({
                "chain": chain,
                "asset": config["asset"],
                "network": config["network"],
                "address": address,
                "status": asset_status,
                "verificationLevel": "limited" if limited_atomic else "full",
                "confirmedAtomic": str(confirmed_atomic),
                "confirmed": format_atomic(confirmed_atomic, precision),
                "pendingAtomic": str(pending_atomic),
                "pending": format_atomic(pending_atomic, precision),
                "limitedTotalAtomic": str(limited_atomic),
                "limitedTotal": format_atomic(limited_atomic, precision),
                "limited": format_atomic(limited_atomic, precision),
                "todayAtomic": str(today_atomic),
                "today": format_atomic(today_atomic, precision),
                "reference": reference,
                "dataAgeSeconds": data_age,
                "lastSuccessAt": last_success,
                "lastObservedAt": last_observed,
            })
            for event in chain_events:
                evidence = self.store.list_evidence(event["eventId"])
                public_events.append(self._public_event(event, config, evidence))

        configured_statuses = [
            asset["status"] for asset in assets if asset["chain"] in configs
        ]
        if not configs:
            status = "partial"
        elif "stale" in configured_statuses:
            status = "stale"
        elif configured_statuses and all(value == "error" for value in configured_statuses):
            status = "error"
        elif any(value != "ok" for value in configured_statuses) or len(configs) < len(SUPPORTED_CHAINS):
            status = "partial"
        else:
            status = "ok"

        public_events.sort(
            key=lambda event: (event.get("blockTime") or 0, event["txid"]), reverse=True
        )
        return {
            "status": status,
            "stale": status == "stale",
            "generatedAt": _iso_utc(now),
            "refreshSeconds": REFRESH_SECONDS,
            "timezone": self.timezone_label,
            "todayStartAt": start.isoformat(),
            "todayEndAt": end.isoformat(),
            "assets": assets,
            "events": public_events,
            "quotes": quotes,
            "messages": messages,
        }

    def health(self):
        return {"ok": True}


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class PayoutRequestHandler(BaseHTTPRequestHandler):
    server_version = "StoneVastPayouts/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _write_json(self, value, status=200, allow=None):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        if self.headers.get("Origin") == PAGES_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", PAGES_ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "GET")
        if allow is not None:
            self.send_header("Allow", allow)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/public/payouts":
            try:
                self._write_json(self.server.service.get_snapshot())
            except Exception as error:
                sys.stderr.write("payout snapshot failed error=%s\n" % type(error).__name__)
                self._write_json({"status": "error", "messages": [{"code": "snapshot_failed"}]}, 500)
            return
        if path == "/api/public/payouts/health":
            self._write_json(self.server.service.health())
            return
        self._write_json({"error": "not_found"}, 404)

    def do_POST(self):
        self._write_json({"error": "method_not_allowed"}, 405, "GET")

    def do_OPTIONS(self):
        self._write_json({"error": "method_not_allowed"}, 405, "GET")


def create_http_server(service, address=BIND):
    server = ThreadingHTTPServer(address, PayoutRequestHandler)
    server.service = service
    return server


def _refresh_loop(service, stop):
    while not stop.is_set():
        service.refresh()
        stop.wait(REFRESH_SECONDS)


def main():
    configs = load_chain_configs(os.environ)
    store = PayoutStore(os.environ.get("STONEVAST_PAYOUT_DB", DEFAULT_DB_PATH))
    service = PayoutService(
        store=store,
        configs=configs,
        adapters=build_default_adapters(configs, os.environ),
    )
    stop = threading.Event()
    refresh_thread = threading.Thread(target=_refresh_loop, args=(service, stop))
    refresh_thread.daemon = True
    refresh_thread.start()
    server = create_http_server(service)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
