"""In-process pub/sub bridging background simulations to WebSocket clients."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Set


class EventHub:
    def __init__(self, history_size: int = 200) -> None:
        self._queues: Set[asyncio.Queue] = set()
        self._history: List[Dict[str, Any]] = []
        self._history_size = history_size
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    @property
    def history(self) -> List[Dict[str, Any]]:
        return list(self._history)

    @property
    def client_count(self) -> int:
        return len(self._queues)

    def publish(self, event_type: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": payload or {},
        }
        self._history.append(event)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

        # Sync endpoints run in a worker thread, so hand delivery back to the
        # event loop rather than touching asyncio.Queue from another thread.
        if self._loop is not None and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._deliver, event)
                return event
            except RuntimeError:
                pass
        self._deliver(event)
        return event

    def _deliver(self, event: Dict[str, Any]) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # A slow client must never stall the safety pipeline.
                self._queues.discard(q)


hub = EventHub()
