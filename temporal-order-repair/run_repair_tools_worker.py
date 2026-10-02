import asyncio
import logging

from temporalio.worker import Worker

import tenuo_repair
from shared.config import get_temporal_client

'''Repair tools worker (optional: Tenuo warrants).
Runs the three repair tools, one Activity each, on the repair-tools task queue.
Tenuo's Temporal plugin checks every call before the tool runs: a warrant chain back to the
trusted root, not expired, covering this tool with these arguments, proof of possession from the
workflow worker, and the approvers' signatures where the warrant asks for them. A call without all
of that never runs. Every decision gets a signed receipt in receipts/repair-tools.jsonl.
See tenuo_repair.py.'''


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not tenuo_repair.load_tools_keys():
        raise SystemExit("No tenuo-tools.env: run `python tenuo_repair.py keygen` first.")

    client = await get_temporal_client()
    receipts = None
    if tenuo_repair.cloud():
        # Tenuo Cloud: receipts, heartbeats and this worker's place in the authorization graph.
        plugin = tenuo_repair.repair_tools_worker_plugin(
            control_plane=tenuo_repair.tenuo_cloud_control_plane())
    else:
        runtime = tenuo_repair.repair_tools_runtime()
        plugin = tenuo_repair.repair_tools_worker_plugin(runtime=runtime)
        receipts = asyncio.create_task(tenuo_repair.write_receipts(runtime))
    worker = Worker(
        client,
        task_queue=tenuo_repair.REPAIR_TOOLS_TASK_QUEUE,
        activities=list(tenuo_repair.REPAIR_TOOL_ACTIVITIES.values()),
        plugins=[plugin],
    )
    print(f"Starting repair tools worker on [{tenuo_repair.REPAIR_TOOLS_TASK_QUEUE}] (warrant required), "
          f"receipts in {tenuo_repair.RECEIPTS_FILE.relative_to(tenuo_repair.ROOT)}...")
    try:
        await worker.run()
    finally:
        if receipts:
            receipts.cancel()


if __name__ == "__main__":
    asyncio.run(main())
