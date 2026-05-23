#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastmcp>=2.0",
#   "yfinance>=0.2.50",
#   "tradingview-screener>=0.3.0",
#   "pandas>=2.0",
#   "tabulate>=0.9",
# ]
# ///

"""
Quick smoke tests for all 4 markets-mcp tools.
Run with: uv run test_markets.py
"""

import sys

# -- import the tools directly from the server module
from markets_server import (
    get_company_financials,
    get_market_price_history,
    get_options_chain,
    screen_market,
)

PASS = "✅"
FAIL = "❌"
results: list[tuple[str, bool, str]] = []


def run(label: str, fn, *args, **kwargs):
    print(f"\n{'─'*60}")
    print(f"▶  {label}")
    print('─'*60)
    try:
        out = fn(*args, **kwargs)
        ok = isinstance(out, str) and len(out) > 20 and "Error" not in out[:50]
        print(out[:800] + (" …[truncated]" if len(out) > 800 else ""))
        results.append((label, ok, ""))
        print(f"\n{PASS if ok else FAIL}  {label}")
    except Exception as exc:
        results.append((label, False, str(exc)))
        print(f"{FAIL}  {label} — EXCEPTION: {exc}")


# ── 1. screen_market (NSE large-cap value) ──────────────────────────────────
run(
    "screen_market — NSE large-cap (PE < 20, mcap > 5B USD)",
    screen_market,
    filters=[
        {"field": "market_cap_basic", "op": ">",  "value": 5_000_000_000},
        {"field": "price_earnings_ttm", "op": "<", "value": 20},
    ],
    exchange="NSE",
    limit=10,
)

# ── 2. screen_market (NASDAQ high relative volume) ──────────────────────────
run(
    "screen_market — NASDAQ high relative volume",
    screen_market,
    filters=[
        {"field": "relative_volume_10d_calc", "op": ">", "value": 2},
        {"field": "close", "op": ">", "value": 10},
    ],
    exchange="NASDAQ",
    limit=8,
)

# ── 3. get_company_financials ────────────────────────────────────────────────
run("get_company_financials — RELIANCE.NS", get_company_financials, "RELIANCE.NS")
run("get_company_financials — AAPL",        get_company_financials, "AAPL")

# ── 4. get_market_price_history ──────────────────────────────────────────────
run("get_market_price_history — TCS.NS 3mo", get_market_price_history, "TCS.NS",  period="3mo")
run("get_market_price_history — NVDA 6mo",   get_market_price_history, "NVDA",    period="6mo")
run("get_market_price_history — Gold 1y",    get_market_price_history, "GC=F",    period="1y")
run("get_market_price_history — USDINR 1mo", get_market_price_history, "USDINR=X",period="1mo")

# ── 5. get_options_chain ─────────────────────────────────────────────────────
run("get_options_chain — AAPL (nearest expiry)", get_options_chain, "AAPL")
run("get_options_chain — SPY  (nearest expiry)", get_options_chain, "SPY")

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'═'*60}")
print("SUMMARY")
print('═'*60)
passed = sum(1 for _, ok, _ in results if ok)
for label, ok, err in results:
    status = PASS if ok else FAIL
    detail = f"  ← {err}" if err else ""
    print(f"  {status}  {label}{detail}")
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
