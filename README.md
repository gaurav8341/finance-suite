# finance-suite

Custom MCP server for financial analysis, focused on **Indian (NSE/BSE)** and **US (NYSE/NASDAQ)** markets.

> Architecture design: [`dev_journal/random_notes/finance_mcp/idea.md`](../dev_journal/random_notes/finance_mcp/idea.md)

---

## markets-mcp

### Tools

| Tool | Description |
|---|---|
| `screen_market` | Filter entire exchange by fundamentals/technicals via TradingView |
| `get_company_financials` | Annual income statement, balance sheet, cash flow + key ratios |
| `get_market_price_history` | Historical OHLCV for stocks, ETFs, commodities, forex |
| `get_options_chain` | Calls + Puts chain with IV, volume, open interest |

### Requirements

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) — manages dependencies via PEP 723 inline metadata, no venv needed

### Running

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run the server — uv auto-installs all dependencies on first run
uv run markets_server.py
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

Add to your `claude_desktop_config.json` or `mcp_config.json`:

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

---

## Dependencies (auto-managed by uv)

- `fastmcp` — MCP server framework
- `yfinance` — Yahoo Finance data (financials, price history, options)
- `tradingview-screener` — TradingView market screener
- `pandas` + `tabulate` — data wrangling and markdown output
