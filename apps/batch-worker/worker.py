"""バッチワーカーメインモジュール（Push型 Pub/Sub対応）.

Pub/SubからのHTTP POSTリクエストを受信し、PDF処理を実行する。
"""

import base64
import json
from datetime import UTC, datetime

import redis
from flask import Flask, request
from loguru import logger

from config import Settings
from processor import PDFProcessor
from storage import get_storage_client

# Flask アプリケーション初期化
app = Flask(__name__)

# 設定読み込み
settings = Settings()
logger.info("Worker starting with settings:")
logger.info(f"  STORAGE_TYPE: {settings.storage_type}")
logger.info(f"  REDIS_HOST: {settings.redis_host}:{settings.redis_port}")
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


@app.route("/", methods=["POST"])
def handle_pubsub_message() -> tuple[str, int]:
    """Pub/SubからのPushメッセージを処理する.

    Push型 Pub/Sub は以下のJSONフォーマットでPOSTリクエストを送信:
    {
        "message": {
            "data": "base64エンコードされたメッセージ",
            "messageId": "...",
            "publishTime": "..."
        },
        "subscription": "..."
    }

    Returns:
        tuple[str, int]: レスポンスメッセージとステータスコード
    """
    job_id: str | None = None

    try:
        # リクエストボディからPub/Subメッセージを取得
        envelope = request.get_json()
        if not envelope:
            logger.error("No JSON body received")
            return "Bad Request: no JSON body", 400

        # Pub/Subメッセージを抽出
        if "message" not in envelope:
            logger.error("Invalid Pub/Sub message format: missing 'message' field")
            return "Bad Request: missing message field", 400

        pubsub_message = envelope["message"]

        # Base64エンコードされたデータをデコード
        if "data" not in pubsub_message:
            logger.error("Invalid Pub/Sub message: missing 'data' field")
            return "Bad Request: missing data field", 400

        message_data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        logger.info(f"Received message: {message_data}")

        # メッセージパース
        message_dict = json.loads(message_data)
        job_id = message_dict.get("job_id")
        pdf_path = message_dict.get("pdf_path")

        if not job_id or not pdf_path:
            logger.error(f"Invalid message format: {message_dict}")
            return "Bad Request: missing job_id or pdf_path", 400

        logger.info(f"Processing job {job_id}, PDF: {pdf_path}")

        # 処理実行
        processor = PDFProcessor(job_id, pdf_path, storage_client, redis_client)
        result_path = processor.process()

        logger.info(f"Job {job_id} completed. Result: {result_path}")

        # 成功レスポンス（Pub/Subに ACK を返す）
        return "OK", 200

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)

        # エラーステータスをRedisに記録（TTL: 24時間）
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
                # TTL 24時間（86400秒）を設定
                redis_client.setex(job_key, 86400, json.dumps(error_status))
                logger.info(f"Error status saved to Redis for job {job_id}")
            except Exception as redis_error:
                logger.error(f"Failed to update error status in Redis: {redis_error}")

        # エラーレスポンス（Pub/Subに ACK を返す。リトライしない）
        # 1度失敗したジョブは再実行せず、failedステータスで終了
        return "OK", 200


@app.route("/health", methods=["GET"])
def health_check() -> tuple[str, int]:
    """ヘルスチェックエンドポイント.

    Returns:
        tuple[str, int]: レスポンスメッセージとステータスコード
    """
    return "OK", 200


if __name__ == "__main__":
    # 本番環境では gunicorn で起動するため、このブロックは開発用
    import os

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
