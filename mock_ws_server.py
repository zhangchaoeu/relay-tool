from __future__ import annotations

import asyncio
import json

import websockets


async def handle(ws: websockets.WebSocketServerProtocol) -> None:
    raw = await ws.recv()
    print("register:", raw)

    task = {
        "type": "task",
        "task_id": "task-1",
        "action": "fs.list",
        "payload": {"path": "."},
    }
    await ws.send(json.dumps(task))

    while True:
        result = await ws.recv()
        print("incoming:", result)


async def main() -> None:
    async with websockets.serve(handle, "127.0.0.1", 8765):
        print("Mock server on ws://127.0.0.1:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
