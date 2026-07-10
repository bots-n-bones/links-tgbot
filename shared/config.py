from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str = ""
    allowed_user_ids: str = ""  # comma-separated telegram_id list, see allowed_user_id_list
    admin_user_id: str = ""  # telegram_id, see admin_user_id_int
    run_mode: str = "polling"  # polling | webhook
    telegram_webhook_secret: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_model_mini: str = "gpt-4o-mini"
    openai_model_report: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/linkcollector"
    redis_url: str = "redis://localhost:6379/0"

    # App
    dashboard_url: str = "http://localhost:8000"
    basic_auth_user: str = "admin"
    basic_auth_pass: str = ""

    # Schedule
    batch_cron_hours: str = "8,20"
    collection_cron_day: str = "mon"
    collection_cron_hour: int = 9

    env: str = "dev"

    @property
    def allowed_user_id_list(self) -> list[int]:
        return [int(x) for x in self.allowed_user_ids.split(",") if x.strip()]

    @property
    def admin_user_id_int(self) -> int | None:
        return int(self.admin_user_id) if self.admin_user_id.strip() else None

    @property
    def batch_cron_hour_list(self) -> list[int]:
        return [int(h) for h in self.batch_cron_hours.split(",") if h.strip()]

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
