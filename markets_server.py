#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastmcp>=2.0",
#   "yfinance>=0.2.50",
#   "tradingview-screener>=0.3.0",
#   "pandas>=2.0",
#   "tabulate>=0.9",
#   "matplotlib>=3.7",
# ]
# ///

"""
Markets & Asset Intelligence MCP Server
========================================
Bottom-up financial asset profiling for Indian (BSE/NSE)
and US (NYSE/NASDAQ) markets.

Tools:
  screen_market            – Filter stocks by fundamentals/technicals (TradingView)
  get_company_financials   – Income statement, balance sheet, cash flow (yfinance)
  get_market_price_history – Historical OHLCV for stocks, ETFs, commodities, forex
  get_options_chain        – Calls/Puts chain with IV, volume, open interest

Run with:
  uv run markets_server.py
"""

from __future__ import annotations

import io
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import yfinance as yf
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from tradingview_screener import Query
from tradingview_screener import col as tv_col

mcp = FastMCP(
    name="markets-mcp",
    instructions=(
        "Use this server to analyse financial markets. "
        "For Indian stocks add the .NS (NSE) or .BO (BSE) suffix to tickers. "
        "US stocks use plain symbols (AAPL, MSFT). "
        "Commodities: GC=F (Gold), CL=F (Oil). Forex: EURUSD=X, USDINR=X."
    ),
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

EXCHANGE_MARKET_MAP: dict[str, str] = {
    "NSE":     "india",
    "BSE":     "india",
    "NYSE":    "america",
    "NASDAQ":  "america",
    "INDIA":   "india",
    "AMERICA": "america",
    "US":      "america",
}

_OP_MAP: dict[str, Any] = {
    ">":       lambda f, v: tv_col(f) > v,
    "<":       lambda f, v: tv_col(f) < v,
    ">=":      lambda f, v: tv_col(f) >= v,
    "<=":      lambda f, v: tv_col(f) <= v,
    "==":      lambda f, v: tv_col(f) == v,
    "between": lambda f, v: tv_col(f).between(*v),
}


def _df_to_markdown(df: pd.DataFrame, max_rows: int = 50) -> str:
    """Return a compact markdown table, truncated to max_rows."""
    if df is None or df.empty:
        return "_No data available._"
    return df.head(max_rows).to_markdown(index=True)


def _fmt_large(x: Any) -> str:
    """Format large numbers as 1.23T / 4.56B / 789M / 12.3K."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "N/A"
    if pd.isna(x):
        return "N/A"
    ax = abs(x)
    if ax >= 1e12:
        return f"{x/1e12:.2f}T"
    if ax >= 1e9:
        return f"{x/1e9:.2f}B"
    if ax >= 1e6:
        return f"{x/1e6:.1f}M"
    if ax >= 1e3:
        return f"{x/1e3:.1f}K"
    return f"{x:.2f}"


# ---------------------------------------------------------------------------
# Tool 1 – screen_market
# ---------------------------------------------------------------------------

@mcp.tool()
def screen_market(
    filters: list[dict[str, Any]],
    exchange: str = "NSE",
    columns: list[str] | None = None,
    limit: int = 25,
    raw: bool = False,
) -> str:
    """
    Screen the entire market by fundamental or technical filters.

    Args:
        filters:  List of filter dicts. Each dict must contain:
                    "field" – TradingView column name (see common fields below)
                    "op"    – one of: ">", "<", ">=", "<=", "==", "between"
                    "value" – scalar value, or [min, max] list for "between"

                  Common fields:
                    market_cap_basic             Market cap in USD
                    price_earnings_ttm           Trailing P/E
                    price_book_ratio             Price-to-book
                    debt_to_equity               D/E ratio
                    return_on_equity             ROE (0–1 scale, e.g. 0.15 = 15%)
                    earnings_per_share_basic_ttm EPS (TTM)
                    close                        Last traded price
                    volume                       Daily volume
                    relative_volume_10d_calc     Volume vs 10-day average
                    sector                       Sector name string

        exchange: One of NSE | BSE | NYSE | NASDAQ  (default: NSE)
        columns:  Additional TradingView columns to include in the output.
        limit:    Maximum rows to return (default 25, hard cap 200).
        raw:      If True, return JSON for chaining with plot_chart.
                  Format: {"labels": [ticker,...], "series": [{"name": col, "values": [...]}]}

    Returns:
        Markdown table of matching stocks with key metrics.
        If raw=True, returns JSON ready for plot_chart.

    Examples:
        Large-cap Indian value stocks:
          filters=[{"field":"market_cap_basic","op":">","value":1e10},
                   {"field":"price_earnings_ttm","op":"<","value":15}],
          exchange="NSE"

        High-volume US momentum stocks above $10:
          filters=[{"field":"relative_volume_10d_calc","op":">","value":2},
                   {"field":"close","op":">","value":10}],
          exchange="NASDAQ"
    """
    market = EXCHANGE_MARKET_MAP.get(exchange.upper(), "india")

    default_cols = [
        "name", "close", "volume", "market_cap_basic",
        "price_earnings_ttm", "price_book_ratio",
        "return_on_equity", "debt_to_equity", "sector",
    ]
    fetch_cols = list(dict.fromkeys(default_cols + (columns or [])))

    conditions = []
    for flt in filters:
        field = flt.get("field")
        op    = flt.get("op")
        value = flt.get("value")
        if not field or not op:
            return "Error: each filter dict must have 'field' and 'op' keys."
        if op not in _OP_MAP:
            return f"Error: unsupported operator '{op}'. Use one of: {list(_OP_MAP)}"
        conditions.append(_OP_MAP[op](field, value))

    try:
        q = (
            Query()
            .select(*fetch_cols)
            .set_markets(market)
            .limit(min(int(limit), 200))
        )
        if conditions:
            q = q.where(*conditions)
        count, df = q.get_scanner_data()
    except Exception as exc:
        return f"Screener error: {exc}"

    if df.empty:
        return f"No stocks found matching the given filters on **{exchange}**."

    if raw:
        import json
        labels = df["ticker"].tolist() if "ticker" in df.columns else df.index.tolist()
        numeric_cols = [c for c in df.columns if c not in ("ticker",) and pd.api.types.is_numeric_dtype(df[c])]
        series = [{"name": c, "values": df[c].tolist()} for c in numeric_cols]
        return json.dumps({"labels": labels, "series": series})

    if "market_cap_basic" in df.columns:
        df["market_cap_basic"] = df["market_cap_basic"].apply(_fmt_large)

    header = (
        f"**{exchange} Screen** — {count} total matches, "
        f"showing top {len(df)}\n\n"
    )
    return header + _df_to_markdown(df)


# ---------------------------------------------------------------------------
# Tool 2 – get_company_financials
# ---------------------------------------------------------------------------

_INCOME_ROWS = [
    "Total Revenue", "Gross Profit", "Operating Income",
    "EBITDA", "Net Income", "Basic EPS", "Diluted EPS",
]
_BS_ROWS = [
    "Total Assets", "Total Liabilities Net Minority Interest",
    "Total Equity Gross Minority Interest", "Cash And Cash Equivalents",
    "Total Debt", "Long Term Debt", "Current Debt", "Net Debt",
]
_CF_ROWS = [
    "Operating Cash Flow", "Investing Cash Flow",
    "Financing Cash Flow", "Free Cash Flow", "Capital Expenditure",
]
_RATIO_KEYS = [
    "trailingPE", "forwardPE", "priceToBook", "returnOnEquity",
    "debtToEquity", "currentRatio", "dividendYield", "beta",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "marketCap",
]
# Human-readable labels for key ratios
_RATIO_LABELS = {
    "trailingPE":       "Trailing P/E",
    "forwardPE":        "Forward P/E",
    "priceToBook":      "Price / Book",
    "returnOnEquity":   "Return on Equity",
    "debtToEquity":     "Debt / Equity (%)",
    "currentRatio":     "Current Ratio",
    "dividendYield":    "Dividend Yield",
    "beta":             "Beta",
    "fiftyTwoWeekHigh": "52-Week High",
    "fiftyTwoWeekLow":  "52-Week Low",
    "marketCap":        "Market Cap",
}


def _slice_and_fmt(df: pd.DataFrame | None, wanted_rows: list[str]) -> pd.DataFrame | None:
    """Keep only wanted rows and format all numbers as B/M strings."""
    if df is None or df.empty:
        return None
    present = [r for r in wanted_rows if r in df.index]
    if not present:
        return None
    df = df.loc[present].copy()
    for col_name in df.columns:
        df[col_name] = df[col_name].apply(_fmt_large)
    # Shorten column headers to YYYY-MM-DD (they're often Timestamps)
    df.columns = [str(c)[:10] for c in df.columns]
    return df


@mcp.tool()
def get_company_financials(ticker: str, period: str = "annual", raw: bool = False) -> str:
    """
    Fetch income statement, balance sheet, and cash flow for a company.

    Args:
        ticker: Stock symbol.
                  NSE  →  append .NS   e.g. "RELIANCE.NS", "TCS.NS", "INFY.NS"
                  BSE  →  append .BO   e.g. "500325.BO"
                  US   →  plain symbol e.g. "AAPL", "MSFT", "GOOGL"
        period: "annual" (default) — last 4 fiscal years
                "quarterly"        — last 4 quarters (TTM view)

        raw:    If True, return JSON for chaining with plot_chart.
                Format: {"labels": [dates], "sections": {"Income Statement": {"Total Revenue": [...]}, ...}}

    Returns:
        Structured markdown with income statement, balance sheet, cash flow, ratios.
        If raw=True, returns JSON ready for plot_chart.
    """
    import json as _json
    t = yf.Ticker(ticker)
    is_quarterly = period.lower().startswith("q")
    period_label = "Quarterly" if is_quarterly else "Annual"

    if is_quarterly:
        sections = [
            ("Income Statement", lambda: t.quarterly_income_stmt, _INCOME_ROWS),
            ("Balance Sheet",    lambda: t.quarterly_balance_sheet, _BS_ROWS),
            ("Cash Flow",        lambda: t.quarterly_cashflow,      _CF_ROWS),
        ]
    else:
        sections = [
            ("Income Statement", lambda: t.income_stmt, _INCOME_ROWS),
            ("Balance Sheet",    lambda: t.balance_sheet, _BS_ROWS),
            ("Cash Flow",        lambda: t.cashflow,      _CF_ROWS),
        ]

    # ── raw JSON mode ──────────────────────────────────────────────────────────
    if raw:
        result: dict[str, Any] = {"ticker": ticker, "period": period_label, "sections": {}}
        labels_set = False
        for title, fetch_fn, wanted in sections:
            try:
                df = fetch_fn()
                if df is None or df.empty:
                    continue
                present = [r for r in wanted if r in df.index]
                if not present:
                    continue
                sub = df.loc[present]
                if not labels_set:
                    result["labels"] = [str(c)[:10] for c in sub.columns]
                    labels_set = True
                result["sections"][title] = {
                    row: [None if pd.isna(v) else float(v) for v in sub.loc[row]]
                    for row in present
                }
            except Exception:
                continue
        if not result["sections"]:
            return _json.dumps({"error": f"No financial data for {ticker}"})
        return _json.dumps(result)

    # ── markdown mode (default) ────────────────────────────────────────────────
    output: list[str] = [f"## Financials ({period_label}) — {ticker}\n"]
    any_data = False

    for title, fetch_fn, wanted in sections:
        try:
            df = _slice_and_fmt(fetch_fn(), wanted)
            if df is not None:
                any_data = True
                output.append(f"### {title}\n")
                output.append(_df_to_markdown(df) + "\n")
        except Exception as exc:
            output.append(f"### {title}\n_Error: {exc}_\n")

    if not any_data:
        return (
            f"No financial data found for `{ticker}`. "
            "For NSE stocks use the `.NS` suffix (e.g. `RELIANCE.NS`)."
        )

    # Key ratios from .info
    try:
        info = t.info
        ratios = {k: info[k] for k in _RATIO_KEYS if info.get(k) is not None}
        if ratios:
            ratio_df = pd.DataFrame.from_dict(ratios, orient="index", columns=["Value"])
            ratio_df["Value"] = [
                _fmt_large(v) if k == "marketCap" else (
                    f"{v:.2f}%" if k == "dividendYield" else (
                        f"{v:.2f}" if isinstance(v, float) else str(v)
                    )
                )
                for k, v in ratios.items()
            ]
            ratio_df.index = [_RATIO_LABELS.get(k, k) for k in ratios]
            output.append("### Key Ratios\n")
            output.append(_df_to_markdown(ratio_df) + "\n")
    except Exception:
        pass

    return "\n".join(output)


# ---------------------------------------------------------------------------
# Tool 3 – get_market_price_history
# ---------------------------------------------------------------------------

_INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}


@mcp.tool()
def get_market_price_history(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    raw: bool = False,
) -> str:
    """
    Fetch historical OHLCV price data for stocks, ETFs, commodities, or forex.

    Args:
        ticker:   Symbol. Examples:
                    Indian stocks : "RELIANCE.NS", "TCS.NS"
                    US stocks     : "AAPL", "TSLA", "NVDA"
                    ETFs          : "SPY", "QQQ", "NIFTYBEES.NS"
                    Gold futures  : "GC=F"
                    Crude oil     : "CL=F"
                    Forex         : "EURUSD=X", "USDINR=X"

        period:   Time range — 1d | 5d | 1mo | 3mo | 6mo | 1y | 2y | 5y | 10y | ytd | max

        interval: Bar size —
                    Intraday (period ≤ 60d): 1m | 2m | 5m | 15m | 30m | 60m | 90m | 1h
                    Daily+               : 1d | 5d | 1wk | 1mo | 3mo

        raw:      If True, return JSON for chaining with plot_chart.
                  Format: {"labels": [...], "series": [{"name": "Close", "values": [...]}, ...]}

    Returns:
        Summary stats + markdown table of last 30 bars.
        If raw=True, returns JSON with Close, High, Low, Open, Volume series.
    """
    import json as _json
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception as exc:
        return f"Error fetching data for `{ticker}`: {exc}"

    if hist.empty:
        return (
            f"No price history for `{ticker}` (period={period}, interval={interval}). "
            "Check the symbol, or note that intraday intervals require period ≤ 60d."
        )

    if raw:
        is_intraday = interval in _INTRADAY_INTERVALS
        fmt = "%Y-%m-%d %H:%M" if is_intraday else "%Y-%m-%d"
        labels = [d.strftime(fmt) for d in hist.index]
        series = [
            {"name": col, "values": [None if pd.isna(v) else round(float(v), 4) for v in hist[col]]}
            for col in ["Close", "Open", "High", "Low", "Volume"] if col in hist.columns
        ]
        return _json.dumps({"ticker": ticker, "labels": labels, "series": series})

    latest  = hist["Close"].iloc[-1]
    first   = hist["Close"].iloc[0]
    ret_pct = (latest / first - 1) * 100
    hi      = hist["High"].max()
    lo      = hist["Low"].min()
    avg_vol = hist["Volume"].mean()

    summary = (
        f"## Price History — {ticker}  ({period} / {interval})\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Latest Close | {latest:.2f} |\n"
        f"| Period Return | {ret_pct:+.2f}% |\n"
        f"| Period High | {hi:.2f} |\n"
        f"| Period Low | {lo:.2f} |\n"
        f"| Avg Daily Volume | {avg_vol:,.0f} |\n"
        f"| Total Bars | {len(hist)} |\n\n"
    )

    display = hist[["Open", "High", "Low", "Close", "Volume"]].tail(30).round(2).copy()
    is_intraday = interval in _INTRADAY_INTERVALS
    try:
        fmt = "%Y-%m-%d %H:%M" if is_intraday else "%Y-%m-%d"
        display.index = display.index.strftime(fmt)
    except Exception:
        pass

    return summary + "### Recent Bars (last 30)\n\n" + _df_to_markdown(display)


# ---------------------------------------------------------------------------
# Tool 4 – get_options_chain
# ---------------------------------------------------------------------------

_OPTIONS_COLS = [
    "strike", "lastPrice", "bid", "ask",
    "impliedVolatility", "volume", "openInterest", "inTheMoney",
]


@mcp.tool()
def get_options_chain(ticker: str, expiry_date: str | None = None) -> str:
    """
    Fetch the full options chain (Calls + Puts) for a stock.

    Note: Works best for US-listed stocks (NYSE / NASDAQ).
          NSE options data via yfinance is very limited.

    Args:
        ticker:      Stock symbol — e.g. "AAPL", "TSLA", "SPY", "QQQ", "NIFTY50.NS"
        expiry_date: Expiry in YYYY-MM-DD format.
                     Omit to use the nearest available expiry automatically.

    Returns:
        List of available expiries + Calls and Puts tables:
        strike | lastPrice | bid | ask | impliedVolatility | volume | openInterest | inTheMoney
    """
    t = yf.Ticker(ticker)

    try:
        expirations: tuple[str, ...] = t.options
    except Exception as exc:
        return f"Could not fetch options for `{ticker}`: {exc}"

    if not expirations:
        return f"No options data available for `{ticker}`."

    if expiry_date:
        if expiry_date not in expirations:
            return (
                f"Expiry `{expiry_date}` not found for `{ticker}`.\n"
                f"Available expiries: {', '.join(expirations[:12])}"
            )
        chosen = expiry_date
    else:
        chosen = expirations[0]

    try:
        chain = t.option_chain(chosen)
    except Exception as exc:
        return f"Error fetching chain for `{ticker}` expiry `{chosen}`: {exc}"

    def _fmt_chain(df: pd.DataFrame, label: str) -> str:
        df = df[[c for c in _OPTIONS_COLS if c in df.columns]].copy()
        if "impliedVolatility" in df.columns:
            df["impliedVolatility"] = (
                (df["impliedVolatility"] * 100).round(1).astype(str) + "%"
            )
        df = df.sort_values("strike").reset_index(drop=True)
        return f"### {label}\n\n" + _df_to_markdown(df, max_rows=40)

    exp_preview = ", ".join(expirations[:12]) + (" …" if len(expirations) > 12 else "")
    header = (
        f"## Options Chain — {ticker}  |  Expiry: **{chosen}**\n\n"
        f"**All available expiries:** {exp_preview}\n\n"
    )
    return header + _fmt_chain(chain.calls, "Calls") + "\n\n" + _fmt_chain(chain.puts, "Puts")


# ---------------------------------------------------------------------------
# Tool 5 – get_field_history
# ---------------------------------------------------------------------------

@mcp.tool()
def get_field_history(
    ticker: str,
    field: str,
    periods: int = 4,
    period_type: str = "quarterly",
    raw: bool = False,
) -> str:
    """
    Get the value of a single financial field across multiple periods.

    Searches income statement, balance sheet, and cash flow automatically.

    Args:
        ticker:      Stock symbol — e.g. "HINDUNILVR.NS", "AAPL"
        field:       Exact row name from the financial statements. Examples:
                       "Total Debt", "Net Debt", "Long Term Debt", "Current Debt"
                       "Total Revenue", "Net Income", "EBITDA", "Free Cash Flow"
                       "Operating Cash Flow", "Capital Expenditure"
                       "Total Assets", "Cash And Cash Equivalents"
        periods:     Number of periods to return (default 4, max 20)
        period_type: "quarterly" (default) or "annual"
        raw:         If True, return JSON for chaining with plot_chart.
                     Format: {"name": "...", "labels": [...], "values": [...]}

    Returns:
        Markdown table + period-over-period % change.
        If raw=True, returns JSON: {"name", "labels", "values"}.
    """
    import json as _json
    t = yf.Ticker(ticker)
    is_quarterly = period_type.lower().startswith("q")
    n = min(int(periods), 20)

    if is_quarterly:
        statements = [
            t.quarterly_income_stmt,
            t.quarterly_balance_sheet,
            t.quarterly_cashflow,
        ]
        label = "Quarterly"
    else:
        statements = [
            t.income_stmt,
            t.balance_sheet,
            t.cashflow,
        ]
        label = "Annual"

    # Search across all statements for the field (case-insensitive)
    series = None
    found_in = None
    stmt_names = ["Income Statement", "Balance Sheet", "Cash Flow"]

    for stmt, name in zip(statements, stmt_names):
        if stmt is None or stmt.empty:
            continue
        # Exact match first
        if field in stmt.index:
            series = stmt.loc[field]
            found_in = name
            break
        # Case-insensitive fallback
        match = [r for r in stmt.index if r.lower() == field.lower()]
        if match:
            series = stmt.loc[match[0]]
            found_in = name
            field = match[0]  # use canonical name
            break

    if series is None:
        # Show available fields across all statements
        all_fields: list[str] = []
        for stmt in statements:
            if stmt is not None and not stmt.empty:
                all_fields.extend(stmt.index.tolist())
        close = [f for f in all_fields if field.lower() in f.lower()]
        hint = ""
        if close:
            hint = f"\n\nDid you mean one of these?\n" + "\n".join(f"  • {f}" for f in close[:10])
        if raw:
            return _json.dumps({"error": f"Field `{field}` not found", "suggestions": close[:10]})
        return f'Field `{field}` not found in any financial statement for `{ticker}`.{hint}'

    # Trim to requested number of periods and sort newest first
    series = series.iloc[:n]
    dates = [str(d)[:10] for d in series.index]
    values = series.values

    if raw:
        raw_vals = [None if pd.isna(v) else float(v) for v in values]
        # Return oldest-first for plotting
        return _json.dumps({"name": field, "labels": list(reversed(dates)), "values": list(reversed(raw_vals))})

    # Build output table
    rows = []
    for i, (date, val) in enumerate(zip(dates, values)):
        fmt_val = _fmt_large(val)
        if i < len(values) - 1:
            prev = values[i + 1]
            try:
                fval, fprev = float(val), float(prev)
                if pd.isna(fval) or pd.isna(fprev) or fprev == 0:
                    chg_str = "N/A"
                else:
                    chg = (fval / fprev - 1) * 100
                    chg_str = f"{chg:+.1f}%"
            except Exception:
                chg_str = "N/A"
        else:
            chg_str = "—"
        rows.append({"Period": date, field: fmt_val, "QoQ Change" if is_quarterly else "YoY Change": chg_str})

    df = pd.DataFrame(rows).set_index("Period")
    header = (
        f"## {field} — {ticker}  ({label}, last {len(rows)} periods)\n"
        f"_Source: {found_in}_\n\n"
    )
    return header + _df_to_markdown(df)


# ---------------------------------------------------------------------------
# Tool 6 – get_ownership_and_trades
# ---------------------------------------------------------------------------

_HIGH_VOL_PERCENTILE = 90   # flag top 10% transactions by share count


@mcp.tool()
def get_ownership_and_trades(ticker: str, top_n: int = 10) -> str:
    """
    Full ownership and registered-entity trading activity for a stock.

    Uses all 6 yfinance ownership tables:
      1. Ownership Overview      — % held by insiders vs institutions, # of institutions
      2. 6-Month Trade Summary   — net buy/sell count + share totals (insider_purchases)
      3. Top Institutional Holders — largest institutional positions with % change
      4. Top Mutual Fund Holders   — largest MF positions with % change
      5. 🚨 Large Trades         — top 10% transactions by share count (any entity)
      6. Top Buyers              — entities with highest total shares acquired
      7. Top Sellers             — entities with highest total shares disposed
      8. Current Holder Roster   — who currently holds shares + last transaction
      9. Recent Transactions     — last 15 chronologically

    Args:
        ticker: Stock symbol — e.g. "HDFCBANK.NS", "RELIANCE.NS", "AAPL"
        top_n:  Rows in buyers/sellers/holders tables (default 10)

    Note:
        For Indian ADR stocks (e.g. HDFC Bank trades as HDB on NYSE),
        yfinance reports ADR-price transactions in USD. Share counts and
        relative volume comparisons remain valid regardless of currency.
    """
    t = yf.Ticker(ticker)
    output: list[str] = [f"## Ownership & Trades — {ticker}\n"]
    any_data = False

    # ── helpers ───────────────────────────────────────────────────────────────
    def _norm_tx(raw: pd.DataFrame) -> pd.DataFrame:
        """Normalise insider_transactions column names and types."""
        col_map = {
            "Start Date": "date", "startDate": "date",
            "Shares": "shares",   "shares": "shares",
            "Value":  "value",    "value":  "value",
            "Text":   "text",     "text":   "text",
            "Insider":"entity",   "filerName": "entity",
            "Position":"position","filerRelation": "position",
            "Transaction": "txn_type",
        }
        df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})
        df["shares"] = pd.to_numeric(df.get("shares", 0), errors="coerce").fillna(0).astype(int)
        df["value"]  = pd.to_numeric(df.get("value",  0), errors="coerce").fillna(0)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
        else:
            df["date_str"] = "N/A"
        text = df.get("text", pd.Series([""] * len(df), index=df.index))
        df["is_buy"]  = text.str.contains("Acquisition|Purchase|Buy",  case=False, na=False)
        df["is_sell"] = text.str.contains("Sale|Sell|Disposition",     case=False, na=False)
        return df

    # ── 1. Ownership Overview ─────────────────────────────────────────────────
    try:
        mh = t.major_holders
        if mh is not None and not mh.empty:
            any_data = True
            mh.index = ["Insider % held", "Institution % held",
                        "Institution float % held", "# Institutions"][:len(mh)]
            mh.columns = ["Value"]
            mh["Value"] = mh["Value"].apply(
                lambda x: f"{x:.2%}" if isinstance(x, float) and x < 2 else str(x)
            )
            output.append("### Ownership Overview\n")
            output.append(_df_to_markdown(mh) + "\n")
    except Exception:
        pass

    # ── 2. 6-Month Trade Summary ──────────────────────────────────────────────
    try:
        ip = t.insider_purchases
        if ip is not None and not ip.empty:
            any_data = True
            output.append("### 6-Month Trade Summary\n")
            output.append(_df_to_markdown(ip) + "\n")
    except Exception:
        pass

    # ── 3. Top Institutional Holders ──────────────────────────────────────────
    try:
        ih = t.institutional_holders
        if ih is not None and not ih.empty:
            any_data = True
            ih = ih.copy()
            if "Value" in ih.columns:
                ih["Value"] = ih["Value"].apply(_fmt_large)
            if "pctHeld" in ih.columns:
                ih["pctHeld"] = ih["pctHeld"].apply(lambda x: f"{x:.2%}" if isinstance(x, float) else x)
            if "pctChange" in ih.columns:
                ih["pctChange"] = ih["pctChange"].apply(lambda x: f"{x:+.2%}" if isinstance(x, float) else x)
            if "Shares" in ih.columns:
                ih["Shares"] = ih["Shares"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "N/A")
            output.append(f"### Top Institutional Holders\n")
            output.append(_df_to_markdown(ih.head(top_n)) + "\n")
    except Exception:
        pass

    # ── 4. Top Mutual Fund Holders ────────────────────────────────────────────
    try:
        mf = t.mutualfund_holders
        if mf is not None and not mf.empty:
            any_data = True
            mf = mf.copy()
            if "Value" in mf.columns:
                mf["Value"] = mf["Value"].apply(_fmt_large)
            if "pctHeld" in mf.columns:
                mf["pctHeld"] = mf["pctHeld"].apply(lambda x: f"{x:.2%}" if isinstance(x, float) else x)
            if "pctChange" in mf.columns:
                mf["pctChange"] = mf["pctChange"].apply(lambda x: f"{x:+.2%}" if isinstance(x, float) else x)
            if "Shares" in mf.columns:
                mf["Shares"] = mf["Shares"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "N/A")
            output.append(f"### Top Mutual Fund Holders\n")
            output.append(_df_to_markdown(mf.head(top_n)) + "\n")
    except Exception:
        pass

    # ── Load & normalise all registered transactions ───────────────────────────
    try:
        raw_tx = t.insider_transactions
        if raw_tx is None or raw_tx.empty:
            raise ValueError("no data")
        tx = _norm_tx(raw_tx)
    except Exception:
        tx = pd.DataFrame()

    if not tx.empty:
        any_data = True
        active = tx[tx["shares"] > 0].copy()
        buys   = active[active["is_buy"]]
        sells  = active[active["is_sell"]]

        # ── 5. Large Trades ───────────────────────────────────────────────────
        if not active.empty:
            threshold = active["shares"].quantile(_HIGH_VOL_PERCENTILE / 100)
            large = active[active["shares"] >= threshold].sort_values("shares", ascending=False)
            if not large.empty:
                hv = large[["date_str", "entity", "position", "shares", "value", "text"]].copy()
                hv.columns = ["Date", "Entity", "Role", "Shares", "Value", "Action"]
                hv["Shares"] = hv["Shares"].apply(lambda x: f"{x:,}")
                hv["Value"]  = hv["Value"].apply(_fmt_large)
                hv["Action"] = hv["Action"].str.slice(0, 50)
                output.append(
                    f"### 🚨 Large Trades — Top {100 - _HIGH_VOL_PERCENTILE}% "
                    f"by share count (≥ {threshold:,.0f} shares)\n"
                )
                output.append(_df_to_markdown(hv.reset_index(drop=True), max_rows=20) + "\n")

        # ── 6. Top Buyers ─────────────────────────────────────────────────────
        if not buys.empty:
            tb = (buys.groupby("entity")
                  .agg(Shares=("shares","sum"), Value=("value","sum"),
                       Txns=("shares","count"), Latest=("date","max"))
                  .sort_values("Shares", ascending=False).head(top_n))
            tb["Shares"] = tb["Shares"].apply(lambda x: f"{x:,}")
            tb["Value"]  = tb["Value"].apply(_fmt_large)
            tb["Latest"] = tb["Latest"].dt.strftime("%Y-%m-%d")
            output.append("### 🟢 Top Buyers (by total shares acquired)\n")
            output.append(_df_to_markdown(tb) + "\n")
        else:
            output.append("### 🟢 Top Buyers\n_No buy transactions recorded._\n")

        # ── 7. Top Sellers ────────────────────────────────────────────────────
        if not sells.empty:
            ts = (sells.groupby("entity")
                  .agg(Shares=("shares","sum"), Value=("value","sum"),
                       Txns=("shares","count"), Latest=("date","max"))
                  .sort_values("Shares", ascending=False).head(top_n))
            ts["Shares"] = ts["Shares"].apply(lambda x: f"{x:,}")
            ts["Value"]  = ts["Value"].apply(_fmt_large)
            ts["Latest"] = ts["Latest"].dt.strftime("%Y-%m-%d")
            output.append("### 🔴 Top Sellers (by total shares disposed)\n")
            output.append(_df_to_markdown(ts) + "\n")
        else:
            output.append("### 🔴 Top Sellers\n_No sell transactions recorded._\n")

        # ── 8. Current Holder Roster ──────────────────────────────────────────
        try:
            roster = t.insider_roster_holders
            if roster is not None and not roster.empty:
                r = roster[["Name","Position","Most Recent Transaction",
                            "Latest Transaction Date","Shares Owned Directly"]].copy()
                r["Shares Owned Directly"] = r["Shares Owned Directly"].apply(
                    lambda x: f"{int(x):,}" if pd.notna(x) else "N/A"
                )
                output.append("### Current Holder Roster\n")
                output.append(_df_to_markdown(r) + "\n")
        except Exception:
            pass

        # ── 9. Recent Transactions ────────────────────────────────────────────
        recent = tx.sort_values("date", ascending=False).head(15)
        rc = recent[["date_str","entity","position","shares","value","text"]].copy()
        rc.columns = ["Date","Entity","Role","Shares","Value","Action"]
        rc["Shares"] = rc["Shares"].apply(lambda x: f"{x:,}")
        rc["Value"]  = rc["Value"].apply(_fmt_large)
        rc["Action"] = rc["Action"].str.slice(0, 45)
        output.append("### Recent Transactions (last 15)\n")
        output.append(_df_to_markdown(rc.reset_index(drop=True)) + "\n")

    if not any_data:
        return f"No ownership data available for `{ticker}`."

    return "\n".join(output)


# ---------------------------------------------------------------------------
# Tool 7 – get_analyst_data
# ---------------------------------------------------------------------------

@mcp.tool()
def get_analyst_data(ticker: str) -> str:
    """
    Fetch forward-looking analyst intelligence for a stock.

    Sections returned (where available):
      - Analyst Price Targets  : mean / high / low / median / current price
      - Recommendations        : period-by-period Buy / Hold / Sell counts
      - EPS Estimates          : consensus EPS for current quarter, next quarter, this year, next year
      - Revenue Estimates      : consensus revenue for same horizons
      - EPS Trend              : how consensus EPS has shifted (current vs 7d/30d/60d/90d ago)
      - EPS Revisions          : # of analyst upgrades vs downgrades in last 7d / 30d
      - Growth Estimates       : expected EPS/revenue growth for each horizon

    Args:
        ticker: Stock symbol.
                  NSE  →  "RELIANCE.NS", "TCS.NS"
                  US   →  "AAPL", "MSFT", "NVDA"

    Returns:
        Markdown report with all available analyst data.
    """
    t = yf.Ticker(ticker)
    output: list[str] = [f"## Analyst Data — {ticker}\n"]
    any_data = False

    # ── 1. Price Targets ──────────────────────────────────────────────────────
    try:
        pt = t.analyst_price_targets
        if pt and isinstance(pt, dict) and len(pt) > 0:
            any_data = True
            pt_df = pd.DataFrame.from_dict(pt, orient="index", columns=["Value"])
            pt_df["Value"] = pt_df["Value"].apply(
                lambda x: f"{x:.2f}" if isinstance(x, float) else str(x)
            )
            output.append("### Analyst Price Targets\n")
            output.append(_df_to_markdown(pt_df) + "\n")
    except Exception:
        pass

    # ── 2. Recommendations Summary ────────────────────────────────────────────
    try:
        rec = t.recommendations_summary
        if rec is not None and not rec.empty:
            any_data = True
            output.append("### Recommendations Summary\n")
            output.append(_df_to_markdown(rec) + "\n")
    except Exception:
        pass

    # ── 3. EPS Estimates ──────────────────────────────────────────────────────
    try:
        eps_est = t.earnings_estimate
        if eps_est is not None and not eps_est.empty:
            any_data = True
            output.append("### EPS Estimates (Consensus)\n")
            output.append(_df_to_markdown(eps_est) + "\n")
    except Exception:
        pass

    # ── 4. Revenue Estimates ──────────────────────────────────────────────────
    try:
        rev_est = t.revenue_estimate
        if rev_est is not None and not rev_est.empty:
            # Format revenue numbers
            rev_fmt = rev_est.copy()
            for col in rev_fmt.columns:
                rev_fmt[col] = rev_fmt[col].apply(
                    lambda x: _fmt_large(x) if isinstance(x, (int, float)) else str(x)
                )
            any_data = True
            output.append("### Revenue Estimates (Consensus)\n")
            output.append(_df_to_markdown(rev_fmt) + "\n")
    except Exception:
        pass

    # ── 5. EPS Trend ──────────────────────────────────────────────────────────
    try:
        trend = t.eps_trend
        if trend is not None and not trend.empty:
            any_data = True
            output.append("### EPS Trend (Consensus Drift)\n")
            output.append(_df_to_markdown(trend) + "\n")
    except Exception:
        pass

    # ── 6. EPS Revisions ─────────────────────────────────────────────────────
    try:
        rev = t.eps_revisions
        if rev is not None and not rev.empty:
            any_data = True
            output.append("### EPS Revisions (Upgrades vs Downgrades)\n")
            output.append(_df_to_markdown(rev) + "\n")
    except Exception:
        pass

    # ── 7. Growth Estimates ───────────────────────────────────────────────────
    try:
        growth = t.growth_estimates
        if growth is not None and not growth.empty:
            growth_fmt = growth.copy()
            for col in growth_fmt.columns:
                growth_fmt[col] = growth_fmt[col].apply(
                    lambda x: f"{x*100:.1f}%" if isinstance(x, float) and abs(x) < 100 else str(x)
                )
            any_data = True
            output.append("### Growth Estimates\n")
            output.append(_df_to_markdown(growth_fmt) + "\n")
    except Exception:
        pass

    if not any_data:
        return (
            f"No analyst data found for `{ticker}`. "
            "This is common for newly listed or thinly covered stocks."
        )

    return "\n".join(output)


# ---------------------------------------------------------------------------
# Tool 8 – get_filings
# ---------------------------------------------------------------------------

# BSE codes for common Indian stocks (ticker → BSE code)
_NSE_TO_BSE: dict[str, str] = {
    "RELIANCE":     "500325",
    "TCS":          "532540",
    "HDFCBANK":     "500180",
    "INFY":         "500209",
    "ICICIBANK":    "532174",
    "HINDUNILVR":   "500696",
    "SBIN":         "500112",
    "BAJFINANCE":   "500034",
    "BHARTIARTL":   "532454",
    "KOTAKBANK":    "500247",
    "WIPRO":        "507685",
    "AXISBANK":     "532215",
    "LT":           "500510",
    "ASIANPAINT":   "500820",
    "MARUTI":       "532500",
    "TITAN":        "500114",
    "SUNPHARMA":    "524715",
    "NESTLEIND":    "500790",
    "ULTRACEMCO":   "532538",
    "TECHM":        "532755",
}


@mcp.tool()
def get_filings(
    ticker: str,
    filing_type: str = "all",
    limit: int = 10,
) -> str:
    """
    Get the latest regulatory filings for a company.

    For US stocks (NYSE/NASDAQ): Returns SEC filings (10-Q, 10-K, 8-K, etc.)
    with direct links to the actual documents via yfinance.

    For Indian stocks (NSE/BSE): yfinance has no filing data. Returns direct
    links to BSE and NSE filing portals for the company.

    Args:
        ticker:       Stock symbol — e.g. "AAPL", "MSFT", "RELIANCE.NS"
        filing_type:  Filter by filing type (US only):
                        "all"  — all filings (default)
                        "10-Q" — quarterly reports
                        "10-K" — annual reports
                        "8-K"  — material events / earnings releases
                        "DEF 14A" — proxy statements
        limit:        Max number of filings to return (default 10, max 30)

    Returns:
        For US stocks: table of filings with date, type, title, and document links.
        For Indian stocks: direct BSE/NSE portal links for the company.
    """
    is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

    # ── Indian stocks — portal links ──────────────────────────────────────────
    if is_indian:
        base = ticker.replace(".NS", "").replace(".BO", "").upper()
        bse_code = _NSE_TO_BSE.get(base)

        output = [f"## Filings — {ticker}\n"]
        output.append(
            "> yfinance does not carry NSE/BSE filing data. "
            "Use the links below to access filings directly.\n"
        )

        output.append("### NSE Filing Portal\n")
        output.append(
            f"- **Corporate Announcements:** "
            f"https://www.nseindia.com/companies-listing/corporate-filings-announcements\n"
            f"- **Financial Results:** "
            f"https://www.nseindia.com/companies-listing/corporate-filings-financial-results\n"
            f"- **Annual Reports:** "
            f"https://www.nseindia.com/companies-listing/corporate-filings-annual-reports\n"
            f"\n_Search for `{base}` on the NSE portal._\n"
        )

        output.append("### BSE Filing Portal\n")
        if bse_code:
            output.append(
                f"- **Quarterly Results:** "
                f"https://www.bseindia.com/stock-share-price/{base.lower()}/{bse_code}/financials-quarterly-results/\n"
                f"- **All Announcements:** "
                f"https://www.bseindia.com/corporates/ann.html?Code={bse_code}\n"
                f"- **Annual Reports:** "
                f"https://www.bseindia.com/bseplus/AnnualReport/{bse_code}/\n"
            )
        else:
            output.append(
                f"- Search for `{base}` at: https://www.bseindia.com/corporates/ann.html\n"
            )

        # Try to get ISIN from yfinance info
        try:
            info = yf.Ticker(ticker).info
            isin = info.get("isin") or info.get("ISIN")
            if isin:
                output.append(f"\n**ISIN:** `{isin}`\n")
            company_name = info.get("longName") or info.get("shortName")
            if company_name:
                output.append(f"**Company:** {company_name}\n")
        except Exception:
            pass

        return "\n".join(output)

    # ── US stocks — SEC filings via yfinance ──────────────────────────────────
    t = yf.Ticker(ticker)
    try:
        filings = t.sec_filings
    except Exception as exc:
        return f"Error fetching filings for `{ticker}`: {exc}"

    if not filings:
        return f"No SEC filings found for `{ticker}`."

    # Filter by type
    ftype = filing_type.upper()
    if ftype != "ALL":
        filings = [f for f in filings if f.get("type", "").upper() == ftype]
        if not filings:
            return f"No `{filing_type}` filings found for `{ticker}`."

    filings = filings[:min(int(limit), 30)]

    output = [f"## SEC Filings — {ticker}\n"]

    rows = []
    for f in filings:
        date     = str(f.get("date", ""))[:10]
        ftype_   = f.get("type", "N/A")
        title    = f.get("title", "")
        exhibits = f.get("exhibits", {})

        # Build clickable links for each exhibit
        links = []
        for ex_type, url in exhibits.items():
            links.append(f"[{ex_type}]({url})")
        link_str = " · ".join(links) if links else f.get("edgarUrl", "N/A")

        rows.append({
            "Date":    date,
            "Type":    ftype_,
            "Title":   title[:60],
            "Documents": link_str,
        })

    df = pd.DataFrame(rows)
    output.append(_df_to_markdown(df, max_rows=30))
    return "\n".join(output)


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

_CHART_STYLE = {
    "bg":        "#0f1117",
    "fg":        "#e0e0e0",
    "grid":      "#2a2a3a",
    "blue":      "#4fc3f7",
    "green":     "#66bb6a",
    "red":       "#ef5350",
    "orange":    "#ffa726",
    "purple":    "#ab47bc",
}


def _apply_dark_style(fig: plt.Figure, axes) -> None:
    """Apply dark theme to figure and all axes."""
    s = _CHART_STYLE
    fig.patch.set_facecolor(s["bg"])
    for ax in (axes if hasattr(axes, "__iter__") else [axes]):
        ax.set_facecolor(s["bg"])
        ax.tick_params(colors=s["fg"], labelsize=8)
        ax.xaxis.label.set_color(s["fg"])
        ax.yaxis.label.set_color(s["fg"])
        ax.title.set_color(s["fg"])
        for spine in ax.spines.values():
            spine.set_edgecolor(s["grid"])
        ax.grid(color=s["grid"], linewidth=0.5, linestyle="--", alpha=0.7)


def _fig_to_image(fig: plt.Figure) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return Image(data=buf.read(), format="png")


# ---------------------------------------------------------------------------
# Tool 8 – plot_price
# ---------------------------------------------------------------------------

@mcp.tool()
def plot_price(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> Image:
    """
    Plot price history as a line chart with volume bars.

    Args:
        ticker:   Stock/ETF/commodity/forex symbol — e.g. "RELIANCE.NS", "AAPL", "GC=F"
        period:   1d | 5d | 1mo | 3mo | 6mo | 1y | 2y | 5y | ytd | max
        interval: 1m | 5m | 15m | 1h | 1d | 1wk | 1mo

    Returns:
        PNG chart — price line + volume bars, dark theme.
    """
    hist = yf.Ticker(ticker).history(period=period, interval=interval)
    if hist.empty:
        raise ValueError(f"No price data for {ticker}")

    s = _CHART_STYLE
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 7),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
    )

    # ── Price line ────────────────────────────────────────────────────────────
    ax1.plot(hist.index, hist["Close"], color=s["blue"], linewidth=1.4, zorder=3)
    ax1.fill_between(hist.index, hist["Close"], hist["Close"].min() * 0.995,
                     alpha=0.12, color=s["blue"])

    latest = hist["Close"].iloc[-1]
    first  = hist["Close"].iloc[0]
    ret    = (latest / first - 1) * 100
    color  = s["green"] if ret >= 0 else s["red"]

    ax1.set_title(
        f"{ticker}   {latest:.2f}   ({ret:+.2f}%)",
        fontsize=13, fontweight="bold", pad=10, color=color,
    )
    ax1.set_ylabel("Price", fontsize=9)
    ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))

    # ── Volume bars ───────────────────────────────────────────────────────────
    vol_colors = [
        s["green"] if c >= o else s["red"]
        for c, o in zip(hist["Close"], hist["Open"])
    ]
    ax2.bar(hist.index, hist["Volume"], color=vol_colors, alpha=0.75, width=0.8)
    ax2.set_ylabel("Volume", fontsize=9)
    ax2.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M" if x >= 1e6 else f"{x/1e3:.0f}K")
    )

    _apply_dark_style(fig, [ax1, ax2])
    plt.tight_layout(h_pad=0.3)
    return _fig_to_image(fig)


# ---------------------------------------------------------------------------
# Tool 9 – plot_chart  (generic, data-source agnostic)
# ---------------------------------------------------------------------------

@mcp.tool()
def plot_chart(
    title: str,
    labels: list[str],
    series: list[dict[str, Any]],
    chart_type: str = "bar",
    y_label: str = "",
    x_label: str = "",
) -> Image:
    """
    Generic chart tool — visualise any data as multiple chart styles.
    Completely data-source agnostic: pass labels + values from anywhere.

    Args:
        title:      Chart title.
        labels:     X-axis labels, e.g. ["2024-Q1", "2024-Q2", "2024-Q3"]
        series:     List of data series. Each entry is a dict:
                      "name"   – legend label
                      "values" – list of numbers (use null for missing points)
                    Example:
                      [
                        {"name": "Revenue",    "values": [150e9, 163e9, 162e9]},
                        {"name": "Net Income", "values": [30e9,  25e9,  28e9]}
                      ]
        chart_type: Chart style — choose one of:
                      "bar"          – grouped bar chart (default, best for comparisons)
                      "stacked_bar"  – stacked bars (best for part-of-whole)
                      "line"         – line with markers (best for trends)
                      "area"         – filled area (best for single series / cumulative)
                      "scatter"      – scatter plot (best for correlation)
                      "barh"         – horizontal bar (best for rankings/categories)
                      "pie"          – pie chart (first series only, uses labels as slices)
        y_label:    Y-axis label (optional).
        x_label:    X-axis label (optional).

    Returns:
        PNG chart image, dark theme.

    Typical workflow:
        1. Fetch data via get_field_history / get_company_financials / screen_market.
        2. Extract the values you need.
        3. Pass them here to visualise.
    """
    if not series:
        raise ValueError("At least one series required.")
    if not labels:
        raise ValueError("Labels cannot be empty.")

    s   = _CHART_STYLE
    pal = [s["blue"], s["green"], s["orange"], s["purple"], s["red"],
           "#26c6da", "#d4e157", "#ec407a"]
    x   = list(range(len(labels)))

    def _clean(values: list) -> list[float]:
        raw = (list(values) + [float("nan")] * len(labels))[:len(labels)]
        return [float(v) if v is not None else float("nan") for v in raw]

    # ── Pie chart (special case) ──────────────────────────────────────────────
    if chart_type == "pie":
        vals  = _clean(series[0].get("values", []))
        clean = [(l, v) for l, v in zip(labels, vals) if not pd.isna(v) and v > 0]
        lbs, vs = zip(*clean) if clean else (labels, vals)
        fig, ax = plt.subplots(figsize=(9, 7))
        wedges, texts, autotexts = ax.pie(
            vs, labels=lbs, autopct="%1.1f%%", startangle=140,
            colors=pal[:len(vs)], textprops={"color": s["fg"], "fontsize": 8},
            wedgeprops={"edgecolor": s["bg"], "linewidth": 1.2},
        )
        for at in autotexts:
            at.set_color(s["bg"])
        ax.set_title(title, fontsize=13, fontweight="bold", color=s["fg"], pad=14)
        fig.patch.set_facecolor(s["bg"])
        ax.set_facecolor(s["bg"])
        return _fig_to_image(fig)

    # ── All other chart types ─────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)

    width = 0.8 / max(len(series), 1)

    for i, ser in enumerate(series):
        name   = ser.get("name", f"Series {i+1}")
        vals   = _clean(ser.get("values", []))
        color  = pal[i % len(pal)]

        if chart_type == "line":
            ax.plot(x, vals, marker="o", linewidth=2,
                    markersize=5, color=color, label=name)

        elif chart_type == "area":
            ax.fill_between(x, vals, alpha=0.30, color=color, label=name)
            ax.plot(x, vals, linewidth=1.8, color=color)

        elif chart_type == "scatter":
            ax.scatter(x, vals, color=color, s=60, alpha=0.85, label=name, zorder=3)

        elif chart_type == "barh":
            y_pos = [yi - (i - (len(series)-1)/2) * width for yi in x]
            ax.barh(y_pos, vals, height=width*0.9, color=color,
                    alpha=0.85, label=name)

        elif chart_type == "stacked_bar":
            bottom = [sum(
                _clean(series[j].get("values", []))[k]
                for j in range(i)
                if not pd.isna(_clean(series[j].get("values", []))[k])
            ) for k in range(len(labels))]
            ax.bar(x, vals, bottom=bottom, color=color, alpha=0.85,
                   label=name, width=0.6)

        else:  # bar (default)
            offset = (i - (len(series)-1) / 2) * width
            bar_x  = [xi + offset for xi in x]
            ax.bar(bar_x, vals, width=width*0.9, color=color,
                   alpha=0.85, label=name)

    # ── Axes formatting ───────────────────────────────────────────────────────
    if chart_type == "barh":
        ax.set_yticks(x)
        ax.set_yticklabels(labels, fontsize=8)
        if x_label: ax.set_xlabel(x_label, fontsize=9)
        if y_label: ax.set_ylabel(y_label, fontsize=9)
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: (
                f"{v/1e12:.1f}T" if abs(v)>=1e12 else
                f"{v/1e9:.1f}B"  if abs(v)>=1e9  else
                f"{v/1e6:.0f}M"  if abs(v)>=1e6  else f"{v:.1f}"
            )
        ))
    else:
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        if x_label: ax.set_xlabel(x_label, fontsize=9)
        if y_label: ax.set_ylabel(y_label, fontsize=9)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: (
                f"{v/1e12:.1f}T" if abs(v)>=1e12 else
                f"{v/1e9:.1f}B"  if abs(v)>=1e9  else
                f"{v/1e6:.0f}M"  if abs(v)>=1e6  else f"{v:.1f}"
            )
        ))

    ax.axhline(0, color=s["fg"], linewidth=0.5, alpha=0.3)
    if len(series) > 1 or chart_type not in ("area",):
        ax.legend(fontsize=9, facecolor=s["bg"], edgecolor=s["grid"],
                  labelcolor=s["fg"])

    _apply_dark_style(fig, ax)
    plt.tight_layout()
    return _fig_to_image(fig)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
