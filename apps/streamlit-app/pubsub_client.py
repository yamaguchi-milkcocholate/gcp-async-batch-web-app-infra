"""Pub/Sub クライアントモジュール.

Cloud Pub/Sub へのメッセージ発行機能を提供する。
ローカル開発時は PUBSUB_EMULATOR_HOST 環境変数でエミュレータに接続する。
"""

import json

from google.cloud import pubsub_v1
from loguru import logger


class PubSubClient:
    """Pub/Sub メッセージ発行クライアント."""

    def __init__(self, project_id: str, topic_name: str) -> None:
        """初期化.

        Args:
            project_id: GCPプロジェクトID
            topic_name: Pub/Subトピック名（例: "pdf-processing-topic"）
        """
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(project_id, topic_name)
        logger.info(f"PubSubClient initialized with topic: {self.topic_path}")

    def publish_message(self, message: dict[str, str]) -> str:
        """メッセージを発行し、メッセージIDを返す.

        Args:
            message: 発行するメッセージ（辞書形式）
                例: {
                    "job_id": "uuid",
                    "pdf_path": "uploads/uuid/file.pdf",
                    "bucket_name": "bucket-name",
                    "timestamp": "2026-02-12T06:30:00Z"
                }

        Returns:
            str: 発行されたメッセージID

        Raises:
            Exception: メッセージ発行に失敗した場合
        """
        message_bytes = json.dumps(message).encode("utf-8")

        try:
            future = self.publisher.publish(self.topic_path, message_bytes)
            message_id = future.result()
            logger.info(f"Published message {message_id}: {message}")
            return message_id
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            raise
