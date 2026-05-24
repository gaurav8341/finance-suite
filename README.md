# finance-suite

Custom MCP server for financial analysis, focused on **Indian (NSE/BSE)** and **US (NYSE/NASDAQ)** markets.

> Architecture design: [`dev_journal/random_notes/finance_mcp/idea.md`](../dev_journal/random_notes/finance_mcp/idea.md)

---

## markets-mcp

### Tools

| Tool | Source | Description |
|---|---|---|
| `screen_market` | TradingView | Filter entire exchange by fundamentals/technicals |
| `get_company_financials` | yfinance | Annual/quarterly income statement, balance sheet, cash flow + key ratios |
| `get_market_price_history` | yfinance | Historical OHLCV for stocks, ETFs, commodities, forex |
| `get_options_chain` | yfinance | Calls + Puts chain with IV, volume, open interest |
| `get_field_history` | yfinance | Single financial field (e.g. Total Debt) across N periods |
| `get_ownership_and_trades` | yfinance | Institutional/insider ownership + large trade activity |
| `get_analyst_data` | yfinance | Price targets, consensus recommendations, EPS/revenue estimates |
| `get_filings` | yfinance / portals | SEC filings with doc links (US); BSE+NSE portal deep links (India) |
| `get_tv_snapshot` | TradingView | ROIC, period returns (1M/3M/6M/YTD/1Y), relative volume |
| `plot_price` | — | Price + volume chart (line + bar, dark theme) |
| `plot_chart` | — | Generic chart from any data: bar, line, area, pie, scatter, barh, stacked bar |

### When to use TradingView vs yfinance

| Metric | Use |
|---|---|
| ROIC | `get_tv_snapshot` — not in yfinance |
| Period returns (1M / 3M / 6M / YTD / 1Y) | `get_tv_snapshot` — not in yfinance |
| Relative volume | `get_tv_snapshot` — not in yfinance |
| Gross/net margins (excluding one-time items) | `get_tv_snapshot` — TradingView normalises these |
| Gross/net margins (as-reported) | `get_company_financials` — yfinance matches reported statements |
| Historical OHLCV, debt, cash flow | `get_market_price_history` / `get_field_history` |
| Analyst coverage, price targets | `get_analyst_data` |
| Cross-stock screening | `screen_market` |

### Requirements

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) — manages dependencies via PEP 723 inline metadata, no venv needed

### Running

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Stdio transport — used by Claude Code / Claude Desktop
uv run markets_server.py

# HTTP/SSE transport — for web clients or ngrok-exposed access
uv run markets_server.py --transport sse --port 8000
# Then expose publicly: ngrok http 8000
```

### Ticker conventions

| Asset class | Example |
|---|---|
| NSE stock | `RELIANCE.NS`, `TCS.NS`, `INFY.NS` |
| BSE stock | `500325.BO` |
| US stock | `AAPL`, `MSFT`, `NVDA` |
| ETF | `SPY`, `QQQ`, `NIFTYBEES.NS` |
| Gold futures | `GC=F` |
| Crude oil | `CL=F` |
| Forex | `EURUSD=X`, `USDINR=X` |

---

## Claude / MCP Config

### Claude Code / Claude Desktop (stdio)

Add to `~/.claude/.mcp.json` (Claude Code) or `claude_desktop_config.json` (Desktop):

```json
{
  "mcpServers": {
    "market-intelligence": {
      "command": "/home/grv/.local/bin/uv",
      "args": ["run", "/home/grv/repos/finance-suite/markets_server.py"]
    }
  }
}
```

### Claude Web (SSE over HTTP)

1. Start the server in SSE mode:
   ```bash
   uv run markets_server.py --transport sse --port 8000
   ```
2. Expose it via ngrok:
   ```bash
   ngrok http 8000
   ```
3. Add the ngrok URL as a remote MCP server in Claude web settings.

---

## Dependencies (auto-managed by uv)

- `fastmcp` — MCP server framework
- `yfinance` — Yahoo Finance data (financials, price history, options, filings)
- `tradingview-screener` — TradingView screener + snapshot data
- `pandas` + `tabulate` — data wrangling and markdown output
- `matplotlib` — chart rendering (dark-theme PNG output)
