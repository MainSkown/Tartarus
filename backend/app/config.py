from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings

type Environment = Literal["development", "production"]
type LogLevel = Literal["critical", "error", "warning", "info", "debug"]


class Settings(BaseSettings):
    database_url: str
    opensearch_url: str
    environment: Environment = "production"
    log_level: LogLevel = "info"
    cape_api_url: str = "http://cape:8000"
    cape_control_url: str = "http://cape:8001"
    cape_api_token: SecretStr | None = None
    cape_storage_path: Path = Path("/cape-storage")
    sample_store_path: Path = Path("/data/samples")
    guest_label: str = "win"
    guacd_host: str = "cape"
    guacd_port: int = 4822
    runner_poll_interval_seconds: float = 2.0
    runner_unreachable_grace_seconds: float = 120.0
    live_poll_interval_seconds: float = 0.25

    @field_validator("log_level", mode="before")
    @classmethod
    def _lowercase_log_level(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields are filled from the environment
