import asyncio
import logging
from temporalio.client import Client
from temporalio.worker import Worker
from dotenv import load_dotenv

import os

import activities
from workflows import RepairAgentWorkflow, RepairAgentWorkflowProactive, RepairAgentWorkflowMonolith, RepairAgentWorkflowSharingContext
from shared.config import TEMPORAL_TASK_QUEUE, get_temporal_client
import tenuo_repair




async def main() -> None:
    
    # Load environment variables
    load_dotenv(override=True)

    # Print LLM configuration info
    llm_model = os.environ.get("LLM_MODEL", "openai/gpt-4")
    print(f"Using LLM Model: {llm_model}")
    
    logging.basicConfig(level=logging.INFO)

    
    try:
        await run_worker()
    finally:
        # Cleanup MCP connections when worker shuts down
        # await mcp_client_manager.cleanup()
        print(f"Cleanup Placeholder")


async def run_worker() -> None:
    # Get a client and init the list of activities
    client = await get_temporal_client()
    # Optional Tenuo warrants: sign proof of possession for repair tools (see tenuo_repair.py).
    plugins, tenuo_activities = [], []
    if tenuo_repair.load_worker_keys():
        plugins = [tenuo_repair.workflow_worker_plugin()]
        # Approval requests are bound to the holder key, so they're opened here.
        tenuo_activities = [tenuo_repair.request_call_approval, tenuo_repair.check_call_approval]
    worker = Worker(
        client,
        task_queue=TEMPORAL_TASK_QUEUE,
        workflows=[RepairAgentWorkflow, RepairAgentWorkflowProactive, RepairAgentWorkflowMonolith, RepairAgentWorkflowSharingContext],
        activities=[activities.single_tool_repair, 
                    activities.detect,
                    activities.analyze, 
                    activities.plan_repair,
                    activities.notify,
                    activities.execute_repairs, 
                    activities.report,
                    activities.process_order,
                    activities.single_agent_repair,
                    activities.load_data,
                    activities.report_with_original_data,
                    tenuo_repair.tenuo_mode,
                    *tenuo_activities],
        plugins=plugins,
    )
    print(f"Starting worker...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
