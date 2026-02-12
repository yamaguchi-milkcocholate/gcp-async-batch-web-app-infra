"""バッチワーカーメインモジュール.

Pub/Subからメッセージをプル方式で受信し、PDF処理を実行する。
"""

import json
import threading
import time
from datetime import UTC, datetime

import redis
from google.cloud import pubsub_v1
from loguru import logger

from config import Settings
from processor import PDFProcessor
from storage import get_storage_client


class AckLeaseExtender:
    """ACK期限を定期的に延長するヘルパークラス.

    長時間処理（30分など）でタイムアウトを防ぐため、
    バックグラウンドスレッドで定期的にACK期限を延長する。
    """

    def __init__(
        self, subscriber: pubsub_v1.SubscriberClient, subscription_path: str, ack_id: str
    ) -> None:
        """初期化.

        Args:
            subscriber: Pub/Subサブスクライバークライアント
            subscription_path: サブスクリプションパス
            ack_id: メッセージのACK ID
        """
        self.subscriber = subscriber
        self.subscription_path = subscription_path
        self.ack_id = ack_id
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """ACK期限延長スレッドを開始する."""
        self.thread = threading.Thread(target=self._extend_loop, daemon=True)
        self.thread.start()
        logger.info("ACK lease extender started")

    def stop(self) -> None:
        """ACK期限延長スレッドを停止する."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)
        logger.info("ACK lease extender stopped")

    def _extend_loop(self) -> None:
        """ACK期限を定期的に延長するループ（5分ごと）."""
        while not self.stop_event.is_set():
            # 5分（300秒）ごとに延長
            if self.stop_event.wait(timeout=300):
                break

            try:
                # ACK期限を600秒（10分）延長
                self.subscriber.modify_ack_deadline(
                    request={
                        "subscription": self.subscription_path,
                        "ack_ids": [self.ack_id],
                        "ack_deadline_seconds": 600,
                    }
                )
                logger.debug(f"Extended ACK deadline for message {self.ack_id}")
            except Exception as e:
                logger.error(f"Failed to extend ACK deadline: {e}")


def main() -> None:
    """メインワーカー処理."""
    # 設定読み込み
    settings = Settings()
    logger.info("Worker starting with settings:")
    logger.info(f"  STORAGE_TYPE: {settings.storage_type}")
    logger.info(f"  REDIS_HOST: {settings.redis_host}:{settings.redis_port}")
    logger.info(f"  PUBSUB_SUBSCRIPTION: {settings.pubsub_subscription}")
    logger.info(f"  GCP_PROJECT_ID: {settings.gcp_project_id}")

    # ストレージクライアント初期化
    storage_client = get_storage_client(settings)

    # Redisクライアント初期化
    redis_client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )
    logger.info("Redis client initialized")

    # Pub/Subサブスクライバー初期化
    subscriber = pubsub_v1.SubscriberClient()

    # プロジェクトIDとサブスクリプション名から完全なパスを構築
    if not settings.gcp_project_id:
        raise ValueError("GCP_PROJECT_ID must be set")

    subscription_path = subscriber.subscription_path(
        settings.gcp_project_id, settings.pubsub_subscription
    )

    logger.info(f"Worker started. Listening to {subscription_path}")

    # メインループ
    while True:
        try:
            # メッセージをプル（最大1件、タイムアウト10秒）
            response = subscriber.pull(
                request={"subscription": subscription_path, "max_messages": 1},
                timeout=10.0,
            )

            if not response.received_messages:
                logger.debug("No messages received, waiting...")
                time.sleep(1)
                continue

            for received_message in response.received_messages:
                message_data = received_message.message.data.decode("utf-8")
                logger.info(f"Received message: {message_data}")

                job_id: str | None = None
                # ACK期限延長スレッド（30分の処理に対応）
                ack_extender = AckLeaseExtender(
                    subscriber, subscription_path, received_message.ack_id
                )

                try:
                    # ACK期限延長を開始
                    ack_extender.start()

                    # メッセージパース
                    message_dict = json.loads(message_data)
                    job_id = message_dict["job_id"]
                    pdf_path = message_dict["pdf_path"]

                    logger.info(f"Processing job {job_id}, PDF: {pdf_path}")

                    # 処理実行
                    processor = PDFProcessor(job_id, pdf_path, storage_client, redis_client)
                    result_path = processor.process()

                    logger.info(f"Job {job_id} completed. Result: {result_path}")

                    # ACK送信
                    subscriber.acknowledge(
                        request={
                            "subscription": subscription_path,
                            "ack_ids": [received_message.ack_id],
                        }
                    )

                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)

                    # エラーステータスをRedisに記録
                    if job_id:
                        try:
                            job_key = f"job:{job_id}"
                            error_status = {
                                "status": "failed",
                                "progress": 0,
                                "message": "Error occurred",
                                "result_url": "",
                                "error_msg": str(e),
                                "updated_at": datetime.now(UTC).isoformat(),
                            }
                            redis_client.set(job_key, json.dumps(error_status))
                            logger.info(f"Error status saved to Redis for job {job_id}")
                        except Exception as redis_error:
                            logger.error(f"Failed to update error status in Redis: {redis_error}")

                    # ACK送信（リトライしない）
                    # 1度失敗したジョブは再実行せず、failedステータスで終了
                    subscriber.acknowledge(
                        request={
                            "subscription": subscription_path,
                            "ack_ids": [received_message.ack_id],
                        }
                    )
                    logger.warning(f"Job {job_id} failed and will not be retried")

                finally:
                    # ACK期限延長スレッドを停止
                    ack_extender.stop()

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
