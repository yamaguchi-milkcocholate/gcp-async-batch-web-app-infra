"""PDF処理モジュール（モック実装）.

PDFのページ数をランダム生成し、各ページの処理を模擬してRedisステータスを更新する。
"""

import json
import random
import time
from datetime import UTC, datetime

import redis
from loguru import logger

from storage import StorageClient


class PDFProcessor:
    """PDF処理クラス（モック実装）."""

    def __init__(
        self, job_id: str, pdf_path: str, storage_client: StorageClient, redis_client: redis.Redis
    ) -> None:
        """初期化.

        Args:
            job_id: ジョブID
            pdf_path: PDFファイルのストレージパス
            storage_client: ストレージクライアント
            redis_client: Redisクライアント
        """
        self.job_id = job_id
        self.pdf_path = pdf_path
        self.storage_client = storage_client
        self.redis_client = redis_client
        # モック: ランダムにページ数を生成
        self.page_count = random.randint(5, 20)
        logger.info(f"[{self.job_id}] PDF has {self.page_count} pages (mock)")

    def process(self) -> str:
        """PDFを処理し、結果ファイルのパスを返す.

        Returns:
            str: 結果ファイルのパス（例: "results/{job_id}/result.json"）

        Raises:
            Exception: 処理中にエラーが発生した場合
        """
        start_time = time.time()

        # 処理開始ステータス更新
        self._update_status(status="processing", progress=0, message="Processing started...")

        # 各ページ処理
        for page_num in range(1, self.page_count + 1):
            # ページ解析シミュレーション（3〜5秒のスリープ）
            sleep_duration = random.uniform(3, 5)
            time.sleep(sleep_duration)

            # 進捗率計算
            progress = int((page_num / self.page_count) * 100)
            message = f"Page {page_num}/{self.page_count} analyzing..."

            # Redis更新
            self._update_status(status="processing", progress=progress, message=message)
            logger.info(f"[{self.job_id}] {message} ({progress}%)")

        # 処理完了
        end_time = time.time()
        processing_time = end_time - start_time

        # 結果ファイル生成
        result_data = {
            "job_id": self.job_id,
            "pages": self.page_count,
            "processed_at": datetime.now(UTC).isoformat(),
            "processing_time_seconds": round(processing_time, 2),
        }

        result_path = f"results/{self.job_id}/result.json"
        result_bytes = json.dumps(result_data, indent=2).encode("utf-8")
        self.storage_client.upload_file(result_bytes, result_path)

        # 完了ステータス更新
        self._update_status(
            status="completed",
            progress=100,
            message="Processing completed!",
            result_url=result_path,
        )

        logger.info(f"[{self.job_id}] Processing completed in {processing_time:.2f}s")
        return result_path

    def _update_status(
        self,
        status: str,
        progress: int,
        message: str,
        result_url: str = "",
        error_msg: str = "",
    ) -> None:
        """Redisにステータスを書き込む（TTL: 24時間）.

        Args:
            status: ステータス（processing, completed, failed）
            progress: 進捗率（0〜100）
            message: ステータスメッセージ
            result_url: 結果ファイルのURL（完了時のみ）
            error_msg: エラーメッセージ（失敗時のみ）
        """
        job_key = f"job:{self.job_id}"
        status_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "result_url": result_url,
            "error_msg": error_msg,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        # TTL 24時間（86400秒）を設定
        self.redis_client.setex(job_key, 86400, json.dumps(status_data))
        logger.debug(f"[{self.job_id}] Status updated: {status} ({progress}%)")
