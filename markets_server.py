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

from typing import Any

import pandas as pd
import yfinance as yf
from fastmcp import FastMCP
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

    Returns:
        Markdown table of matching stocks with key metrics.

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
    "Total Debt", "Net Debt",
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
def get_company_financials(ticker: str, period: str = "annual") -> str:
    """
    Fetch income statement, balance sheet, and cash flow for a company.

    Args:
        ticker: Stock symbol.
                  NSE  →  append .NS   e.g. "RELIANCE.NS", "TCS.NS", "INFY.NS"
                  BSE  →  append .BO   e.g. "500325.BO"
                  US   →  plain symbol e.g. "AAPL", "MSFT", "GOOGL"
        period: "annual" (default) — last 4 fiscal years
                "quarterly"        — last 4 quarters (TTM view)

    Returns:
        Structured markdown with:
          - Income Statement (Revenue → Net Income)
          - Balance Sheet (Assets, Liabilities, Equity, Debt)
          - Cash Flow (Operating, Investing, Financing, FCF)
          - Key Ratios (P/E, P/B, ROE, D/E, Beta, 52-week range …)
        Numbers formatted as B (billions) / M (millions).
    """
    t = yf.Ticker(ticker)
    is_quarterly = period.lower().startswith("q")
    period_label = "Quarterly" if is_quarterly else "Annual"
    output: list[str] = [f"## Financials ({period_label}) — {ticker}\n"]
    any_data = False

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
                    f"{v:.4f}" if isinstance(v, float) else str(v)
                )
                for k, v in ratios.items()
            ]
            output.append("### Key Ratios\n")
            output.append(_df_to_markdown(ratio_df) + "\n")
    except Exception:
        pass

    # Insider transactions
    try:
        ins = t.insider_transactions
        if ins is not None and not ins.empty:
            keep = [c for c in ["startDate", "shares", "value", "text", "filerName", "filerRelation", "transactionText"] if c in ins.columns]
            ins = ins[keep].copy()
            if "startDate" in ins.columns:
                ins["startDate"] = pd.to_datetime(ins["startDate"], unit="s", errors="coerce").dt.strftime("%Y-%m-%d")
            if "value" in ins.columns:
                ins["value"] = ins["value"].apply(_fmt_large)
            output.append("### Insider Transactions (Recent)\n")
            output.append(_df_to_markdown(ins, max_rows=10) + "\n")
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

    Returns:
        Summary stats (return, high, low, avg volume) + markdown table of last 30 bars.
    """
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception as exc:
        return f"Error fetching data for `{ticker}`: {exc}"

    if hist.empty:
        return (
            f"No price history for `{ticker}` (period={period}, interval={interval}). "
            "Check the symbol, or note that intraday intervals require period ≤ 60d."
        )

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
# Tool 5 – get_analyst_data
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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
