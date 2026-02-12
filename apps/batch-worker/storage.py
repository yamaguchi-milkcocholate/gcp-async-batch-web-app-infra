"""ストレージ抽象化レイヤー.

ローカルファイルシステムとGCSを統一的に扱うための抽象化インターフェース。
環境変数 STORAGE_TYPE で動作を切り替える。
"""

from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

from config import Settings


class StorageClient(ABC):
    """ストレージクライアントの抽象基底クラス."""

    @abstractmethod
    def upload_file(self, file_bytes: bytes, destination_path: str) -> str:
        """ファイルをアップロードし、パスを返す.

        Args:
            file_bytes: アップロードするファイルのバイトデータ
            destination_path: 保存先パス（例: "uploads/job-id/file.pdf"）

        Returns:
            str: 保存されたファイルのパス
        """

    @abstractmethod
    def download_file(self, source_path: str) -> bytes:
        """ファイルをダウンロードし、バイトデータを返す.

        Args:
            source_path: ダウンロード元パス

        Returns:
            bytes: ファイルのバイトデータ
        """


class LocalStorageClient(StorageClient):
    """ローカルファイルシステムを使用するストレージクライアント."""

    def __init__(self, base_path: str) -> None:
        """初期化.

        Args:
            base_path: ベースディレクトリパス（例: "./local_storage"）
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalStorageClient initialized with base_path: {self.base_path}")

    def upload_file(self, file_bytes: bytes, destination_path: str) -> str:
        """ローカルファイルシステムにファイルを保存.

        Args:
            file_bytes: ファイルのバイトデータ
            destination_path: 相対パス（base_path からの相対）

        Returns:
            str: 保存されたファイルの相対パス
        """
        full_path = self.base_path / destination_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        full_path.write_bytes(file_bytes)
        logger.info(f"File uploaded to local storage: {full_path}")

        return destination_path

    def download_file(self, source_path: str) -> bytes:
        """ローカルファイルシステムからファイルを読み込み.

        Args:
            source_path: 相対パス（base_path からの相対）

        Returns:
            bytes: ファイルのバイトデータ

        Raises:
            FileNotFoundError: ファイルが存在しない場合
        """
        full_path = self.base_path / source_path

        if not full_path.exists():
            logger.error(f"File not found: {full_path}")
            raise FileNotFoundError(f"File not found: {source_path}")

        file_bytes = full_path.read_bytes()
        logger.info(f"File downloaded from local storage: {full_path}")

        return file_bytes


class GCSStorageClient(StorageClient):
    """Google Cloud Storage を使用するストレージクライアント."""

    def __init__(self, bucket_name: str) -> None:
        """初期化.

        Args:
            bucket_name: GCSバケット名
        """
        from google.cloud import storage

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        logger.info(f"GCSStorageClient initialized with bucket: {bucket_name}")

    def upload_file(self, file_bytes: bytes, destination_path: str) -> str:
        """GCSにファイルをアップロード.

        Args:
            file_bytes: ファイルのバイトデータ
            destination_path: GCS内のパス

        Returns:
            str: アップロードされたファイルのパス
        """
        blob = self.bucket.blob(destination_path)
        blob.upload_from_string(file_bytes)
        logger.info(f"File uploaded to GCS: gs://{self.bucket.name}/{destination_path}")

        return destination_path

    def download_file(self, source_path: str) -> bytes:
        """GCSからファイルをダウンロード.

        Args:
            source_path: GCS内のパス

        Returns:
            bytes: ファイルのバイトデータ

        Raises:
            Exception: ファイルが存在しない場合
        """
        blob = self.bucket.blob(source_path)

        if not blob.exists():
            logger.error(f"File not found in GCS: gs://{self.bucket.name}/{source_path}")
            raise FileNotFoundError(f"File not found: {source_path}")

        file_bytes = blob.download_as_bytes()
        logger.info(f"File downloaded from GCS: gs://{self.bucket.name}/{source_path}")

        return file_bytes


def get_storage_client(settings: Settings) -> StorageClient:
    """設定に基づいて適切なストレージクライアントを返す.

    Args:
        settings: アプリケーション設定

    Returns:
        StorageClient: ストレージクライアントインスタンス

    Raises:
        ValueError: 未知のストレージタイプの場合
    """
    if settings.storage_type == "LOCAL":
        return LocalStorageClient(settings.local_storage_path)
    elif settings.storage_type == "GCP":
        if not settings.gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME must be set when STORAGE_TYPE=GCP")
        return GCSStorageClient(settings.gcs_bucket_name)
    else:
        raise ValueError(f"Unknown storage type: {settings.storage_type}")
