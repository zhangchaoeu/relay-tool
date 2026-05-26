from __future__ import annotations

import asyncio
import json
import logging

import websockets
from websockets.exceptions import WebSocketException

from hermes_gateway.config import GatewayConfig
from hermes_gateway.gateway import Gateway

logger = logging.getLogger(__name__)


class GatewayServer:
    """WebSocket server that listens for the worker connection."""

    def __init__(self, config: GatewayConfig, gateway: Gateway) -> None:
        self.config = config
        self.gateway = gateway

    async def start(self) -> None:
        logger.info(
            "Gateway listening on ws://%s:%d", self.config.host, self.config.port
        )
        async with websockets.serve(
            self._handle_connection,
            self.config.host,
            self.config.port,
            ping_interval=None,
        ):
            await asyncio.Future()  # run until cancelled

    async def _handle_connection(
        self, ws: websockets.WebSocketServerProtocol
    ) -> None:
        """Handle the lifecycle of a single WebSocket connection."""
        remote = ws.remote_address
        logger.info("Incoming connection from %s", remote)
        registered = False

        try:
            # Expect the first message to be a register.
            raw = await ws.recv()
            msg = json.loads(raw)

            if msg.get("type") != "register":
                logger.warning("Expected 'register', got type=%s – closing", msg.get("type"))
                await ws.close(1008, "Expected register message")
                return

            if not self.gateway.handle_register(msg, ws):
                await ws.close(1008, "Authentication failed")
                return

            registered = True

            # Dispatch incoming messages until the connection closes.
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message from worker – ignored")
                    continue

                msg_type = msg.get("type")
                if msg_type == "heartbeat":
                    self.gateway.handle_heartbeat(msg)
                elif msg_type == "task_result":
                    self.gateway.handle_task_result(msg)
                else:
                    logger.debug("Unrecognised message type=%s – ignored", msg_type)

        except WebSocketException as exc:
            logger.info("WebSocket error from %s: %s", remote, exc)
        finally:
            if registered:
                self.gateway.state.disconnect()
            logger.info("Connection from %s closed", remote)
