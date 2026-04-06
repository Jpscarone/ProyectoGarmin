from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "training_app"
    debug: bool = True
    database_url: str = f"sqlite:///{(BASE_DIR / 'training_app.db').as_posix()}"
    garmin_enabled: bool = False
    garmin_email: str | None = None
    garmin_password: str | None = None
    garmin_token_dir: str = str(BASE_DIR / ".garmin_tokens")
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_timeout_sec: float = 30.0
    openai_max_output_tokens_session: int = 800
    openai_max_output_tokens_week: int = 1500

    @field_validator("debug", "garmin_enabled", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no", "off"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
