"""Starts the released alpaca-mcp-server pointed at fake_alpaca instead of paper-api.alpaca.markets.

    python run_server.py                   # the stock server
    python run_server.py --with-tenuo      # the same command behind `python -m tenuo.mcp.wrap`

The URL swap is the only change for the demo; in real use you run
`python -m tenuo.mcp.wrap alpaca-mcp-server` directly.
"""

import os
import sys

import alpaca_mcp_server.server

alpaca_mcp_server.server.TRADING_API_BASE_URLS["paper"] = os.environ["FAKE_ALPACA_URL"]

if __name__ == "__main__":
    if sys.argv[1:] == ["--with-tenuo"]:
        from tenuo.mcp.wrap import main

        main(["alpaca-mcp-server"])
    else:
        from alpaca_mcp_server.cli import main

        sys.argv = ["alpaca-mcp-server"]
        main()
