from __future__ import annotations

import argparse
import asyncio
import logging

from hermes_relay.config import load_config
from hermes_relay.dispatcher import TaskDispatcher
from hermes_relay.mcp.manager import MCPManager
from hermes_relay.security import normalize_allowed_roots
from hermes_relay.services.fs_service import FileService
from hermes_relay.services.powershell_service import PowerShellService
from hermes_relay.worker import WebSocketWorker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hermes Relay worker")
    parser.add_argument("--config", default="config.json", help="Path to relay config JSON")
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    config = load_config(args.config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

    fs = FileService(normalize_allowed_roots(config.allowed_file_roots))
    ps = PowerShellService(config.powershell_allowlist)
    mcp = MCPManager(config)
    await mcp.auto_start()

    dispatcher = TaskDispatcher(fs=fs, powershell=ps, mcp=mcp)
    worker = WebSocketWorker(config=config, dispatcher=dispatcher)
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(_main())
