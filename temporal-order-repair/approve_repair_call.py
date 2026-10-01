import argparse
import asyncio
import base64
import json
import os

from dotenv import load_dotenv
from tenuo import SigningKey

import tenuo_repair
from shared.config import get_temporal_client

'''Approve repair tool calls that are waiting for you (optional: Tenuo warrants).
A restock that is large, or of an item not on the order, runs only once every approver named in
the warrant has signed that exact call: tool, arguments and warrant. One "no" denies it.
The decision goes to the waiting workflow as a Signal. With Tenuo Cloud, approvers decide in the
dashboard or Slack instead, and run_approval_webhook.py sends the Signal.
    python approve_repair_call.py --as store-manager
    python approve_repair_call.py --as finance'''

parser = argparse.ArgumentParser(description="Approve repair tool calls waiting for your signature.")
parser.add_argument("--as", dest="approver", required=True, choices=tenuo_repair.APPROVERS)
parser.add_argument("--yes", action="store_true", help="approve everything pending without asking")
parser.add_argument("--no", action="store_true", help="deny everything pending without asking")
args = parser.parse_args()


def decide(pending: dict) -> bool:
    print(f"\n{pending['tool']} (warrant {pending['warrant_id']}), "
          f"{len(pending['signatures'])} of {pending['needed']} signed:")
    print(json.dumps(pending["arguments"], indent=2))
    if args.yes or args.no:
        return args.yes
    return input("Approve this call? (yes/no): ").strip().lower() in ("y", "yes")


async def main() -> None:
    load_dotenv(tenuo_repair.ROOT / f"tenuo-approver-{args.approver}.env")
    key = SigningKey.from_bytes(base64.b64decode(os.environ["TENUO_APPROVER_KEY"]))
    decided = tenuo_repair.approve_pending(args.approver, key, decide=decide)
    client = await get_temporal_client()
    for workflow_id, decision in decided:
        await client.get_workflow_handle(workflow_id).signal(tenuo_repair.APPROVAL_SIGNAL, decision)
        print(f"Sent {'denied' if 'denied' in decision else 'approved'} to {workflow_id}")


if __name__ == "__main__":
    asyncio.run(main())
