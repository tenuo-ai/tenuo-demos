import asyncio
import logging

from temporalio.worker import Worker

import tenuo_repair
from shared.config import get_temporal_client

'''Issuer worker (optional: Tenuo warrants).
Issues a warrant for one order when a repair workflow is about to repair it: the issuer's own
warrant narrowed to that order's ID, customer and items, for an hour. Its own warrant comes from
tenuo-issuer.env (signed by the root key you keep offline) or, with tenuo-cloud.env, from the
Tenuo Cloud order-repair trigger fired for that order. See tenuo_repair.py.'''


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not tenuo_repair.load_issuer_keys():
        raise SystemExit("No tenuo-issuer.env: run `python create_tenuo_keys.py` first.")

    client = await get_temporal_client()
    worker = Worker(
        client,
        task_queue=tenuo_repair.ISSUER_TASK_QUEUE,
        activities=[tenuo_repair.issue_order_warrant],
    )
    source = "Tenuo Cloud trigger" if tenuo_repair.cloud() else "local issuer warrant"
    print(f"Starting issuer worker on [{tenuo_repair.ISSUER_TASK_QUEUE}] ({source})...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
