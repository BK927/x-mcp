from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_dir: Path = Field(default_factory=lambda: user_data_path("bk927-x-mcp", appauthor=False))
    session_file: Path | None = None
    max_result_bytes: int = Field(default=12_288, ge=4096, le=32_768)
    result_ttl: int = Field(default=3600, ge=60, le=86_400)
    timeout: float = Field(default=30, ge=1, le=30)
    access_token: str = ""
    host: str = "127.0.0.1"
    port: int = Field(default=8766, ge=1, le=65535)
    public_base_url: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        values = {}
        mapping = {
            "X_MCP_STATE_DIR": "state_dir",
            "X_MCP_SESSION_FILE": "session_file",
            "X_MCP_MAX_RESULT_BYTES": "max_result_bytes",
            "X_MCP_RESULT_TTL": "result_ttl",
            "MCP_ACCESS_TOKEN": "access_token",
            "MCP_HOST": "host",
            "MCP_PORT": "port",
            "PUBLIC_BASE_URL": "public_base_url",
        }
        for env, field in mapping.items():
            if os.getenv(env):
                values[field] = os.environ[env]
        return cls.model_validate(values)

    @property
    def cookies_path(self) -> Path:
        return self.session_file or self.state_dir / "session.json"
