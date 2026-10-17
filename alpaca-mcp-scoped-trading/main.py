"""A trading agent on Alpaca's MCP server: paper trading and toolsets vs a task warrant.

The portfolio manager may buy or sell up to 100 shares of AAPL, MSFT or NVDA
per order. It hands an execution agent one task: buy up to 10 AAPL with a day
limit order at no more than $230. The agent's warrant is derived from the
manager's and says exactly that.

The agent then also does what a planted instruction in a news headline would
ask (the server labels news as untrusted, but the model still reads it). The
server's own controls, paper trading plus the trading toolset only, let all of
it through. Behind `python -m tenuo.mcp.wrap`, only the task reaches Alpaca.

Runs offline: fake_alpaca stands in for Alpaca's paper trading API.
"""

import asyncio
import base64
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tenuo import CEL, Exact, OneOf, SigningKey, Warrant, encode_warrant_stack

HERE = Path(__file__).parent

org_key = SigningKey.generate()  # the operator's trust root; the server trusts only this
manager_key = SigningKey.generate()
agent_key = SigningKey.generate()

# Alpaca takes quantities and prices as decimal strings, so caps are CEL over double(value).
UP_TO_100 = "double(value) > 0.0 && double(value) <= 100.0"

manager_warrant = (
    Warrant.mint_builder()
    .capability(
        "place_stock_order",
        {
            "symbol": OneOf(["AAPL", "MSFT", "NVDA"]),
            "side": OneOf(["buy", "sell"]),
            "qty": CEL(UP_TO_100),
            "type": OneOf(["market", "limit"]),
            "limit_price": CEL("double(value) > 0.0"),
            "time_in_force": Exact("day"),
        },
    )
    .holder(manager_key.public_key)
    .ttl(3600)
    .mint(org_key)
)


def agent_warrant_for(symbol: str, max_qty: int, max_price: float) -> Warrant:
    """One symbol, buys only, a share cap and a price cap. Tenuo rejects anything wider than the manager's."""
    return (
        manager_warrant.grant_builder()
        .capability(
            "place_stock_order",
            {
                "symbol": Exact(symbol),
                "side": Exact("buy"),
                # A child CEL must keep the parent's predicate and add to it.
                "qty": CEL(f"({UP_TO_100}) && (double(value) <= {float(max_qty)})"),
                "type": Exact("limit"),
                "limit_price": CEL(f"(double(value) > 0.0) && (double(value) <= {float(max_price)})"),
                "time_in_force": Exact("day"),
            },
        )
        .holder(agent_key.public_key)
        .ttl(900)
        .grant(manager_key)
    )


def tenuo_meta(chain: list[Warrant], key: SigningKey, tool: str, args: dict) -> dict:
    proof = chain[-1].sign(key, tool, args, int(time.time()))
    warrant = chain[0].to_base64() if len(chain) == 1 else encode_warrant_stack(chain)
    return {"tenuo": {"warrant": warrant, "signature": base64.b64encode(bytes(proof)).decode()}}


def order(symbol="AAPL", side="buy", qty="10", type="limit", limit_price="228.50"):
    args = {"symbol": symbol, "side": side, "qty": qty, "type": type, "time_in_force": "day"}
    if limit_price is not None:
        args["limit_price"] = limit_price
    return args


AGENT_CALLS = [
    ("buy 10 AAPL, limit $228.50", "place_stock_order", order()),
    ("buy 10 NVDA", "place_stock_order", order(symbol="NVDA", limit_price="180")),
    ("buy 50 AAPL", "place_stock_order", order(qty="50")),
    ("buy 10 AAPL, limit $900", "place_stock_order", order(limit_price="900")),
    ("buy 10 AAPL at market", "place_stock_order", order(type="market", limit_price=None)),
    ("sell 10 AAPL", "place_stock_order", order(side="sell")),
    ("close all positions", "close_all_positions", {}),
    ("cancel all orders", "cancel_all_orders", {}),
]

NATIVE_SCOPE = {"ALPACA_PAPER_TRADE": "true", "ALPACA_TOOLSETS": "trading"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _alpaca_writes(log: Path) -> list[str]:
    return [line for line in log.read_text().splitlines() if not line.startswith("GET")]


async def run(with_tenuo: bool, calls=AGENT_CALLS, chain=None, key=None, attach=True):
    """Run calls against the server; returns (label, reached_alpaca, is_error, text) and Alpaca's write log."""
    chain = chain or [manager_warrant, agent_warrant_for("AAPL", 10, 230)]
    key = key or agent_key
    log = Path(tempfile.mkstemp()[1])
    port = _free_port()
    alpaca = subprocess.Popen([sys.executable, str(HERE / "fake_alpaca.py"), str(port)], env={**os.environ, "ALPACA_LOG": str(log)})
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "FAKE_ALPACA_URL": f"http://127.0.0.1:{port}",
        "ALPACA_API_KEY": "fake",
        "ALPACA_SECRET_KEY": "fake",
        **NATIVE_SCOPE,
    }
    args = [str(HERE / "run_server.py")]
    if with_tenuo:
        env["TENUO_TRUSTED_ROOT"] = bytes(org_key.public_key.to_bytes()).hex()
        args.append("--with-tenuo")
    results = []
    try:
        params = StdioServerParameters(command=sys.executable, args=args, env=env, cwd=str(HERE))
        async with stdio_client(params, errlog=open(os.devnull, "w")) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for label, tool, call_args in calls:
                    before = len(_alpaca_writes(log))
                    meta = tenuo_meta(chain, key, tool, call_args) if attach else None
                    res = await session.call_tool(tool, call_args, meta=meta)
                    reached = len(_alpaca_writes(log)) > before
                    text = "".join(getattr(b, "text", "") for b in res.content)
                    results.append((label, reached, res.isError, text))
    finally:
        alpaca.kill()
    return results, _alpaca_writes(log)


def report(title: str, results) -> None:
    print(f"\n{title}")
    for label, reached, _, text in results:
        if reached:
            print(f"  {label:28} reached Alpaca")
        else:
            reason = text.replace(" not satisfied", "").replace(": value does not match constraint", "")
            print(f"  {label:28} REFUSED  {reason[:70]}")


def main() -> None:
    scope = ", ".join(f"{k}={v}" for k, v in NATIVE_SCOPE.items())
    results, _ = asyncio.run(run(with_tenuo=False))
    report(f"{scope}:", results)
    results, writes = asyncio.run(run(with_tenuo=True))
    report("same, behind python -m tenuo.mcp.wrap (the agent's warrant: buy <= 10 AAPL, limit <= $230):", results)
    print("\nAlpaca received:")
    for line in writes:
        print(f"  {line}")


if __name__ == "__main__":
    main()
