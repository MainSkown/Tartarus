from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings

type Environment = Literal["development", "production"]
type LogLevel = Literal["critical", "error", "warning", "info", "debug"]


class Settings(BaseSettings):
    database_url: str
    opensearch_url: str
    environment: Environment = "production"
    log_level: LogLevel = "info"

    @field_validator("log_level", mode="before")
    @classmethod
    def _lowercase_log_level(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields are filled from the environment
