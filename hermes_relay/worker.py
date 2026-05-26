from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets
from websockets.exceptions import WebSocketException

from hermes_relay.config import RelayConfig
from hermes_relay.dispatcher import TaskDispatcher

logger = logging.getLogger(__name__)


class WebSocketWorker:
    def __init__(self, config: RelayConfig, dispatcher: TaskDispatcher):
        self.config = config
        self.dispatcher = dispatcher

    async def run_forever(self) -> None:
        while True:
            try:
                await self._run_session()
            except (WebSocketException, OSError, json.JSONDecodeError):
                logger.exception("WebSocket session failed")
            await asyncio.sleep(self.config.reconnect_interval_seconds)

    async def _run_session(self) -> None:
        async with websockets.connect(self.config.ws_server_url, ping_interval=None) as ws:
            await ws.send(json.dumps(self._register_message()))

            heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") != "task":
                        continue
                    result = await self.dispatcher.dispatch(msg)
                    await ws.send(json.dumps(result))
            finally:
                heartbeat_task.cancel()

    async def _heartbeat_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(self.config.heartbeat_interval_seconds)
            payload = {
                "type": "heartbeat",
                "agent_id": self.config.agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await ws.send(json.dumps(payload))

    def _register_message(self) -> dict:
        return {
            "type": "register",
            "agent_id": self.config.agent_id,
            "agent_name": self.config.agent_name,
            "token": self.config.worker_token,
            "capabilities": self.dispatcher.capabilities,
        }
