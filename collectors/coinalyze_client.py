"""Minimal Coinalyze API client (free tier, 40 req/min).

Docs: https://api.coinalyze.net/v1/doc/  Auth: api_key header.
Set COINALYZE_API_KEY in the environment. All timestamps are unix seconds.
"""

from __future__ import annotations

import time

import httpx

from collectors.common import env

BASE_URL = "https://api.coinalyze.net/v1"
BATCH_SIZE = 20  # max symbols per request
REQUEST_INTERVAL_S = 1.6  # stay under 40 req/min


class CoinalyzeClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or env("COINALYZE_API_KEY")
        if not self.api_key:
            raise RuntimeError("COINALYZE_API_KEY is not set")
        self._client = httpx.Client(timeout=30, headers={"api_key": self.api_key})
        self._last_request = 0.0

    def _get(self, path: str, params: dict | None = None):
        for attempt in range(6):
            wait = REQUEST_INTERVAL_S - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            response = self._client.get(f"{BASE_URL}{path}", params=params or {})
            self._last_request = time.monotonic()
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After") or 10 * (attempt + 1))
                time.sleep(min(retry_after, 70))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"coinalyze still rate-limited after retries: {path}")

    def future_markets(self) -> list[dict]:
        return self._get("/future-markets")

    def perp_symbols_for_bases(self, bases: set[str], prefer_aggregated: bool = True) -> dict[str, str]:
        """Map coinalyze market symbol -> base asset, for perps of the given bases.

        With prefer_aggregated, bases that have '.A' (cross-exchange aggregated)
        symbols use only those - far fewer symbols, so far fewer API calls."""
        markets = self.future_markets()
        all_symbols: dict[str, str] = {}
        for market in markets:
            if not market.get("is_perpetual"):
                continue
            base = market.get("base_asset")
            if base in bases and market.get("quote_asset") in {"USDT", "USD", "USDC"}:
                all_symbols[market["symbol"]] = base
        if not prefer_aggregated:
            return all_symbols
        aggregated_bases = {b for s, b in all_symbols.items() if s.endswith(".A")}
        return {s: b for s, b in all_symbols.items()
                if (s.endswith(".A")) or (b not in aggregated_bases)}

    def liquidation_history(self, symbols: list[str], interval: str, start_s: int, end_s: int) -> list[dict]:
        """Returns [{symbol, history: [{t, l, s}]}] with USD-converted long/short totals."""
        results = []
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i : i + BATCH_SIZE]
            results.extend(
                self._get(
                    "/liquidation-history",
                    {
                        "symbols": ",".join(batch),
                        "interval": interval,
                        "from": start_s,
                        "to": end_s,
                        "convert_to_usd": "true",
                    },
                )
            )
        return results

    def open_interest_history(self, symbols: list[str], interval: str, start_s: int, end_s: int) -> list[dict]:
        """Returns [{symbol, history: [{t, o, h, l, c}]}] in USD."""
        results = []
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i : i + BATCH_SIZE]
            results.extend(
                self._get(
                    "/open-interest-history",
                    {
                        "symbols": ",".join(batch),
                        "interval": interval,
                        "from": start_s,
                        "to": end_s,
                        "convert_to_usd": "true",
                    },
                )
            )
        return results
