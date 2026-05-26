from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import websockets

logger = logging.getLogger(__name__)


@dataclass
class WorkerState:
    """Holds the runtime state of the single registered worker."""

    connection: websockets.WebSocketServerProtocol | None = None
    online: bool = False
    last_heartbeat: datetime | None = None
    capabilities: list[str] = field(default_factory=list)
    # Pending task futures keyed by task_id.
    _pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)

    def register(
        self,
        connection: websockets.WebSocketServerProtocol,
        capabilities: list[str],
    ) -> None:
        self.connection = connection
        self.online = True
        self.last_heartbeat = datetime.now(timezone.utc)
        self.capabilities = capabilities
        logger.info("Worker registered with capabilities: %s", capabilities)

    def record_heartbeat(self) -> None:
        self.last_heartbeat = datetime.now(timezone.utc)

    def disconnect(self) -> None:
        self.connection = None
        self.online = False
        logger.info("Worker disconnected; cancelling %d pending tasks", len(self._pending))
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    def add_pending(self, task_id: str, future: asyncio.Future[dict[str, Any]]) -> None:
        self._pending[task_id] = future

    def resolve(self, task_id: str, result: dict[str, Any]) -> None:
        future = self._pending.pop(task_id, None)
        if future and not future.done():
            future.set_result(result)
        else:
            logger.warning("Received result for unknown or already-resolved task_id=%s", task_id)
