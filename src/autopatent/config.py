import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field


class Settings(BaseModel):
    provider: Literal["codex", "api"] = "codex"
    codex_command: str = "codex"
    codex_model: str = ""
    timeout_seconds: float = Field(default=300, gt=0)
    llm_base_url: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = ""
    data_dir: Path = Path("data")

    @classmethod
    def load(cls, env_file: Path = Path(".env")) -> "Settings":
        values = {**dotenv_values(env_file), **os.environ}
        mapping = {
            "provider": "LLM_PROVIDER", "codex_command": "CODEX_COMMAND",
            "codex_model": "CODEX_MODEL", "timeout_seconds": "LLM_TIMEOUT_SECONDS",
            "llm_base_url": "LLM_BASE_URL", "llm_api_key": "LLM_API_KEY",
            "llm_model": "LLM_MODEL", "data_dir": "AUTOPATENT_DATA_DIR",
        }
        return cls(**{key: values[name] for key, name in mapping.items()
                      if values.get(name) not in (None, "")})
