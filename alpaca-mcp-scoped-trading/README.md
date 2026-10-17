# Per-task order limits for a trading agent on Alpaca's MCP server

The portfolio manager may buy or sell up to 100 shares of AAPL, MSFT or NVDA
per order. It hands an execution agent one task: buy up to 10 AAPL with a day
limit order at no more than $230. The agent's warrant is derived from the
manager's and says exactly that.

[alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server) lets you
choose paper or live trading and which toolsets to load, and it labels news
and other third-party text as untrusted. None of that limits what a single
order can be. An agent that follows a planted line in a headline can still buy
a different stock, buy fifty times as much, pay any price, sell, or close every
position.

## Run it

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv run main.py
```

```text
ALPACA_PAPER_TRADE=true, ALPACA_TOOLSETS=trading:
  buy 10 AAPL, limit $228.50   reached Alpaca
  buy 10 NVDA                  reached Alpaca
  buy 50 AAPL                  reached Alpaca
  buy 10 AAPL, limit $900      reached Alpaca
  buy 10 AAPL at market        reached Alpaca
  sell 10 AAPL                 reached Alpaca
  close all positions          reached Alpaca
  cancel all orders            reached Alpaca

same, behind python -m tenuo.mcp.wrap (the agent's warrant: buy <= 10 AAPL, limit <= $230):
  buy 10 AAPL, limit $228.50   reached Alpaca
  buy 10 NVDA                  REFUSED  Constraint 'symbol'
  buy 50 AAPL                  REFUSED  Constraint 'qty'
  buy 10 AAPL, limit $900      REFUSED  Constraint 'limit_price'
  buy 10 AAPL at market        REFUSED  Constraint 'limit_price': missing required argument
  sell 10 AAPL                 REFUSED  Constraint 'side'
  close all positions          REFUSED  Tool 'close_all_positions' is not authorized
  cancel all orders            REFUSED  Tool 'cancel_all_orders' is not authorized

Alpaca received:
  POST /v2/orders {"symbol":"AAPL","side":"buy","type":"limit","time_in_force":"day","qty":"10","limit_price":"228.50"}
```

Both runs are the released `alpaca-mcp-server` over stdio. `fake_alpaca.py`
stands in for Alpaca's paper trading API and records every request, so no
order goes anywhere. `run_server.py` points the server at it; that's the only
change made for the demo.

## What changes in the server

Nothing. You start it through Tenuo's wrapper:

```bash
TENUO_TRUSTED_ROOT=<hex public key> python -m tenuo.mcp.wrap alpaca-mcp-server
```

The wrapper puts Tenuo's FastMCP middleware in front of the server's own, so
every call must carry a warrant chain that leads back to the trusted key, plus
a signature from the key the warrant names. The check is per argument and
closed-world: a market order, which has no `limit_price`, is refused for the
missing argument, and tools the warrant doesn't name don't run.

Alpaca takes quantities and prices as decimal strings, so the caps are CEL
expressions over `double(value)`. They refuse `NaN`, `inf`, hex and anything
that isn't a number. The agent's caps are written as the manager's expression
plus a tighter one, which is how Tenuo checks that a delegated CEL constraint
is narrower.

## Where the warrant comes from

The agent's side holds a key and attaches `_meta.tenuo`; `tenuo_meta()` in
`main.py` shows the format, and agents built with a Tenuo integration or
`tenuo.mcp.SecureMCPClient` do it for you. Callers without a warrant are
refused, so this is for servers serving agents you run.

## Tests

```bash
uv run pytest
```

- paper trading plus the trading toolset alone lets every call through (the baseline)
- with Tenuo, Alpaca receives exactly the one task order, and each refusal names the argument that failed
- odd quantities (`10.5`, `1e9`, `NaN`, `inf`, `-1`, `0`, `0x10`, `abc`) never reach Alpaca
- no warrant, an untrusted root, a stolen warrant without its key, and a child warrant without its parent never reach Alpaca
- the manager can't delegate outside its scope; the agent can't re-delegate wider

Tested with alpaca-mcp-server 2.4.0 (FastMCP 3.4.7) and mcp 1.30. Needs the
tenuo release that includes `tenuo.mcp.wrap`.
