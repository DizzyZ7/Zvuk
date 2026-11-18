from functools import lru_cache
from typing import Annotated
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    bot_token: SecretStr
    telegram_api_id: int
    telegram_api_hash: SecretStr
    admin_ids: Annotated[tuple[int, ...], NoDecode] = ()
    database_url: str
    redis_url: str
    bot_api_url: str = "http://telegram-bot-api:8081"
    spotify_client_id: str = ""
    audd_api_token: SecretStr = SecretStr("")
    recognition_max_input_mb: int = Field(default=20, ge=1, le=100)
    free_recognitions_daily: int = Field(default=3, ge=0, le=100)
    premium_recognitions_daily: int = Field(default=20, ge=1, le=1000)
    premium_price_stars: int = Field(default=149, ge=1, le=100000)
    premium_days: int = Field(default=30, ge=1, le=365)
    support_username: str = ""
    spotify_client_secret: SecretStr = SecretStr("")
    proxies: str = ""
    ytdlp_cookies: str = ""
    max_file_mb: int = Field(default=1990, ge=1, le=1999)
    max_duration_sec: int = Field(default=1800, ge=60, le=14400)
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    max_pending_per_user: int = Field(default=3, ge=1, le=20)
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def split_admins(cls, value):
        if isinstance(value, str):
            return tuple(int(s.strip()) for s in value.split(",") if s.strip())
        return value

    @property
    def proxy_list(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in self.proxies.split(",") if s.strip())

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
