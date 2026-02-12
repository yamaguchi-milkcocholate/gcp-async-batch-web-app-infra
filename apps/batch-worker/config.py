"""設定管理モジュール.

環境変数からアプリケーション設定を読み込む。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション設定."""

    # ストレージ設定
    storage_type: str = "LOCAL"
    local_storage_path: str = "./local_storage"
    gcs_bucket_name: str | None = None

    # Redis設定
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Pub/Sub設定
    pubsub_emulator_host: str | None = None
    pubsub_subscription: str = "pdf-processing-subscription"
    gcp_project_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
