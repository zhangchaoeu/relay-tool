from __future__ import annotations

import argparse
import asyncio
import logging

from hermes_gateway.config import load_config
from hermes_gateway.gateway import Gateway
from hermes_gateway.server import GatewayServer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hermes Gateway – WebSocket server")
    parser.add_argument("--config", default="gateway_config.json", help="Path to gateway config JSON")
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    config = load_config(args.config)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    gateway = Gateway(config)
    server = GatewayServer(config, gateway)
    await server.start()


if __name__ == "__main__":
    asyncio.run(_main())
