"""Event bus for streaming agent activity to the dashboard via SSE."""

import asyncio
import json
import time
from typing import Any

# Global event queue — dashboard SSE endpoint reads from this
_event_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)


async def publish(event: dict):
    """Publish an event to the SSE stream."""
    event.setdefault("timestamp", time.time())
    try:
        _event_queue.put_nowait(event)
    except asyncio.QueueFull:
        # Drop oldest event if queue is full
        try:
            _event_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        _event_queue.put_nowait(event)


async def subscribe():
    """Yield events as SSE data. Used by the /events endpoint."""
    while True:
        event = await _event_queue.get()
        yield {"data": json.dumps(event)}


async def publish_batch(events: list[dict]):
    """Publish multiple events at once."""
    for event in events:
        await publish(event)
