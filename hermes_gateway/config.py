from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8765
    worker_agent_id: str = "windows-32"
    worker_token: str
    default_task_timeout_seconds: int = 30
    heartbeat_timeout_seconds: int = 60


def load_config(path: str | Path) -> GatewayConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return GatewayConfig.model_validate(data)
