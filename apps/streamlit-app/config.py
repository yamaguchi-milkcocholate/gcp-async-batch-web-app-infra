"""設定管理モジュール.

環境変数を pydantic-settings で読み込み、型安全な設定オブジェクトとして提供する。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション設定クラス.

    環境変数または .env ファイルから設定を読み込む。
    """

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
    pubsub_topic: str = "pdf-processing-topic"
    gcp_project_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
