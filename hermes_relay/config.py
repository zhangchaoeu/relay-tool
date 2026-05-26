from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: List[str] = Field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    auto_start: bool = False


class RelayConfig(BaseModel):
    ws_server_url: str
    agent_id: str
    agent_name: str = "Hermes Relay"
    worker_token: str
    heartbeat_interval_seconds: int = 10
    reconnect_interval_seconds: int = 5
    allowed_file_roots: List[str] = Field(default_factory=list)
    powershell_allowlist: List[str] = Field(default_factory=list)
    allowed_npm_packages: List[str] = Field(default_factory=list)
    allowed_pip_packages: List[str] = Field(default_factory=list)
    registry_file: str = "servers.json"
    log_dir: str = "logs"


def load_config(path: str | Path) -> RelayConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return RelayConfig.model_validate(data)
