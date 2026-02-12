# Spec: Batch Worker (Mock PDF Processor)

## 1. 概要

PDF一括解析バッチ処理システムのワーカーコンポーネント。Pub/Subからメッセージをプル方式で受信し、PDFのページ数を取得（モック: ランダム生成）して、各ページの解析を模擬した処理を行い、Redisでステータスを更新し、結果ファイルをストレージに保存する。

## 2. 変更の目的

- **非同期バッチ処理**: Pub/Subキューから取得したジョブを並列処理（複数ワーカー）
- **長時間処理のシミュレーション**: 実際の解析処理を想定したsleep処理によるステータス更新とモック実装
- **リアルタイムフィードバック**: 処理中の進捗をRedisに書き込み、フロントエンドに提供
- **結果配信**: 処理完了後の結果ファイル（JSON）をストレージに保存し、ダウンロード可能にする
- **長時間処理への対応**: ACK期限自動延長により最大30分の処理をサポート
- **信頼性の向上**: 失敗時のリトライなしでステータス管理を明確化

## 3. 技術スタック

- **言語**: Python 3.12+
- **パッケージ管理**: `uv`
- **依存ライブラリ**:
  - `google-cloud-pubsub`: Pub/Subクライアント（メッセージプル）
  - `google-cloud-storage`: GCSクライアント（ストレージ抽象化レイヤー経由）
  - `redis`: Redisクライアント（ステータス更新）
  - `pydantic-settings`: 環境変数管理
  - `loguru`: 構造化ログ出力

## 4. 機能要件

### 4.1. Pub/Subメッセージ受信（Pull型）

- **実装方式**: `subscriber.pull()` を使用してメッセージをポーリング
- **ポーリング間隔**: 継続的にポーリング（ブロッキングモード）
- **メッセージ形式**:

```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "pdf_path": "uploads/f47ac10b-58cc-4372-a567-0e02b2c3d479/document.pdf",
  "bucket_name": "local",
  "timestamp": "2026-02-12T06:30:00Z"
}
```

- **サブスクリプション名**: 環境変数 `PUBSUB_SUBSCRIPTION` で指定（例: `pdf-processing-subscription`）
- **ACK期限**: 600秒（10分）に設定
- **環境切り替え**:
  - ローカル環境: `PUBSUB_EMULATOR_HOST=localhost:8085` 経由
  - 本番環境: 実際のCloud Pub/Sub

#### ACK期限の自動延長

本番環境では最大30分の処理時間を想定し、ACK期限を自動延長する仕組みを実装。

- **AckLeaseExtender クラス**: バックグラウンドスレッドでACK期限を延長
- **延長間隔**: 5分（300秒）ごと
- **延長期限**: 600秒（10分）
- **停止**: 処理完了またはエラー時に自動停止

### 4.2. モックPDF処理

#### ページ数取得（モック）

- **実装**: `random.randint(5, 20)` でページ数をランダム生成
- **ログ出力**: `logger.info(f"PDF has {page_count} pages")`

#### 処理ループ

各ページごとに以下を実行:

1. **ページ解析シミュレーション**: `time.sleep(random.uniform(3, 5))` で3〜5秒のランダムスリープ
2. **Redis進捗更新**:
   - `progress` を計算: `(page_number / page_count) * 100`
   - `message` を更新: `f"Page {page_number}/{page_count} analyzing..."`
   - `updated_at` をISO 8601形式で更新

**処理時間の目安**:

- 5ページ: 15秒〜25秒
- 10ページ: 30秒〜50秒
- 20ページ: 1分〜1分40秒

### 4.3. Redisステータス管理

#### キー形式

```
job:{job_id}
```

#### TTL（有効期限）

- **設定値**: 24時間（86400秒）
- **目的**: 古いジョブデータの自動削除、過去24時間のジョブ履歴管理
- **実装**: Redisの `SETEX` コマンド、または `SET` + `EXPIRE` コマンドで設定

#### データ構造

```json
{
  "status": "processing",
  "progress": 45,
  "message": "Page 5/12 analyzing...",
  "result_url": "",
  "error_msg": "",
  "updated_at": "2026-02-12T06:35:00Z"
}
```

#### 更新タイミング

| タイミング         | status       | progress | message                 | result_url | error_msg        |
| ------------------ | ------------ | -------- | ----------------------- | ---------- | ---------------- |
| **処理開始時**     | `processing` | 0        | "Processing started..." | `""`       | `""`             |
| **各ページ処理後** | `processing` | 計算値   | "Page X/Y analyzing..." | `""`       | `""`             |
| **処理完了時**     | `completed`  | 100      | "Processing completed!" | 結果パス   | `""`             |
| **エラー発生時**   | `failed`     | 停止時点 | "Error occurred"        | `""`       | エラーメッセージ |

**重要:** 各更新時にTTLを再設定し、24時間の有効期限を維持する。

### 4.4. 結果ファイル生成

#### ファイル形式

JSON形式で以下の情報を含む:

```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "pages": 15,
  "processed_at": "2026-02-12T06:35:30Z",
  "processing_time_seconds": 45.2
}
```

#### 保存先パス

- ローカル環境: `./local_storage/results/{job_id}/result.json`
- 本番環境: `gs://{bucket_name}/results/{job_id}/result.json`

#### 実装

1. JSON辞書を作成
2. `json.dumps()` でシリアライズ
3. `storage_client.upload_file()` でアップロード
4. `result_url` をRedisに書き込み: `results/{job_id}/result.json`

### 4.5. エラーハンドリング

#### キャッチすべき例外

- **ストレージエラー**: ファイルアップロード・ダウンロード失敗
- **Redis接続エラー**: ステータス更新失敗
- **Pub/Subエラー**: メッセージのACK/NACK失敗
- **予期しないエラー**: その他の例外

#### エラー時の処理

1. `status` を `failed` に更新
2. `error_msg` にトレースバック情報を含めたエラーメッセージを記録
3. Pub/Subメッセージを `nack()` して再配信を許可（リトライ可能な場合）
4. `logger.error()` でログ出力

### 4.6. メッセージACK

- **処理成功時**: `message.ack()` で確認応答
- **処理失敗時**: `message.ack()` で確認応答（**リトライなし**）
  - 失敗したジョブは再実行せず、`failed` ステータスで終了
  - 同じエラーでの無限リトライを防止

## 5. Docker構成

### 5.1. ディレクトリ構造

```
apps/
└── batch-worker/
    ├── Dockerfile
    ├── pyproject.toml
    ├── worker.py
    ├── config.py
    ├── storage.py  # Streamlitと共有または再実装
    └── processor.py
```

### 5.2. Dockerfile仕様

- **ベースイメージ**: `python:3.12-slim`
- **作業ディレクトリ**: `/app`
- **パッケージインストール**: `uv` を使用
- **エントリーポイント**: `python worker.py`

### 5.3. 環境変数

| 変数名                 | 説明                                 | デフォルト値                  | 例                                                 |
| ---------------------- | ------------------------------------ | ----------------------------- | -------------------------------------------------- |
| `STORAGE_TYPE`         | ストレージタイプ（`LOCAL` or `GCP`） | `LOCAL`                       | `GCP`                                              |
| `LOCAL_STORAGE_PATH`   | ローカルストレージのパス             | `./local_storage`             | `/data`                                            |
| `GCS_BUCKET_NAME`      | GCSバケット名                        | -                             | `pdf-processing-bucket`                            |
| `REDIS_HOST`           | Redisホスト                          | `localhost`                   | `redis`                                            |
| `REDIS_PORT`           | Redisポート                          | `6379`                        | `6379`                                             |
| `REDIS_DB`             | Redis DB番号                         | `0`                           | `0`                                                |
| `PUBSUB_EMULATOR_HOST` | Pub/Subエミュレータホスト            | -                             | `localhost:8085`                                   |
| `PUBSUB_SUBSCRIPTION`  | Pub/Subサブスクリプション名          | `pdf-processing-subscription` | `projects/my-project/subscriptions/pdf-processing` |
| `GCP_PROJECT_ID`       | GCPプロジェクトID                    | -                             | `my-gcp-project`                                   |

### 5.4. Docker Compose設定

```yaml
services:
  worker:
    build:
      context: ./apps/batch-worker
      dockerfile: Dockerfile
    volumes:
      - ./apps/batch-worker:/app
      - ./local_storage:/app/local_storage
    environment:
      - STORAGE_TYPE=LOCAL
      - LOCAL_STORAGE_PATH=./local_storage
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - PUBSUB_EMULATOR_HOST=pubsub:8085
      - PUBSUB_SUBSCRIPTION=pdf-processing-subscription
      - GCP_PROJECT_ID=local-dev
    depends_on:
      - redis
      - pubsub
    deploy:
      replicas: 3  # 3つのワーカーを並列起動
```

## 6. コード設計

### 6.1. モジュール構成

#### `config.py` - 設定管理

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
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
```

#### `storage.py` - ストレージ抽象化レイヤー

Streamlitアプリと同じ実装を使用。必要に応じてコピーまたは共有モジュール化。

#### `processor.py` - PDF処理ロジック（モック）

```python
import random
import time
import json
from datetime import datetime, UTC
from loguru import logger

class PDFProcessor:
    def __init__(self, job_id: str, pdf_path: str, storage_client, redis_client):
        self.job_id = job_id
        self.pdf_path = pdf_path
        self.storage_client = storage_client
        self.redis_client = redis_client
        self.page_count = random.randint(5, 20)
        logger.info(f"PDF has {self.page_count} pages (mock)")

    def process(self) -> str:
        """
        PDFを処理し、結果ファイルのパスを返す
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
        """Redisにステータスを書き込む（TTL: 24時間）"""
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
```

#### `worker.py` - メインワーカー

```python
import json
import threading
import time
from datetime import UTC, datetime
from google.cloud import pubsub_v1
import redis
from loguru import logger
from config import Settings
from storage import get_storage_client
from processor import PDFProcessor


class AckLeaseExtender:
    """ACK期限を定期的に延長するヘルパークラス.

    長時間処理（30分など）でタイムアウトを防ぐため、
    バックグラウンドスレッドで定期的にACK期限を延長する。
    """

    def __init__(
        self, subscriber: pubsub_v1.SubscriberClient, subscription_path: str, ack_id: str
    ) -> None:
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


def main():
    settings = Settings()
    storage_client = get_storage_client(settings)
    redis_client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )

    # Pub/Subサブスクライバー初期化
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(
        settings.gcp_project_id, settings.pubsub_subscription
    )

    logger.info(f"Worker started. Listening to {subscription_path}")

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
                            redis_client.setex(job_key, 86400, json.dumps(error_status))
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
```

## 7. テスト方法

### 7.1. ローカル開発環境での動作確認

1. **サブスクリプション作成**（docker-compose.ymlで自動作成）:

`docker-compose.yml`のpubsubサービスで自動的にトピックとサブスクリプションを作成：

```yaml
# ACK期限600秒で作成
curl -X PUT http://localhost:8085/v1/projects/local-dev/subscriptions/pdf-processing-subscription \
  -H 'Content-Type: application/json' \
  -d '{"topic": "projects/local-dev/topics/pdf-processing-topic", "ackDeadlineSeconds": 600}'
```

2. **Docker Composeで全サービス起動**:

```bash
docker compose up -d
```

3つのワーカーが並列起動されます。

3. **Streamlitからジョブ投入**:
   - ブラウザで `http://localhost:8501` にアクセス
   - PDFファイルをアップロードして「解析開始」ボタンをクリック

4. **ワーカーログ確認**（全ワーカー）:

```bash
docker compose logs -f worker
```

5. **並列処理の確認**:

複数のPDFを投入して、3つのワーカーが同時に処理することを確認：

```bash
# 5つのジョブを投入
for i in 1 2 3 4 5; do
  curl -X POST http://localhost:8085/v1/projects/local-dev/topics/pdf-processing-topic:publish \
    -H 'Content-Type: application/json' \
    -d "{\"messages\": [{\"data\": \"$(echo '{\"job_id\":\"test-'$i'\",\"pdf_path\":\"test.pdf\"}' | base64)\"}]}"
done

# 並列処理を確認
docker compose logs worker | grep "Processing job"
```

6. **進捗表示確認**:
   - Streamlit UIで進捗バーとメッセージが2秒ごとに更新されることを確認

7. **結果ファイル確認**:

```bash
cat local_storage/results/{job_id}/result.json
```

### 7.2. Redisステータス確認

```bash
docker exec -it gcp-async-batch-web-app-infra-redis-1 redis-cli
GET job:{job_id}
```

## 8. 非機能要件

- **スケーラビリティ**: 複数ワーカーコンテナを起動して並列処理（デフォルト3並列）
  - `docker compose up -d --scale worker=5` でワーカー数を動的に変更可能
- **長時間処理**: ACK期限自動延長により最大30分以上の処理に対応
- **信頼性**: 失敗時のリトライなしで無限ループを防止
- **冪等性**: 同じメッセージを複数回受信しても結果が変わらない設計（リトライなしで実現）
- **エラーハンドリング**: 例外発生時もACK送信でジョブを完了、Redisにfailedステータスを記録
- **ログ出力**: `loguru` で構造化ログを出力（INFO, ERROR レベル）
- **タイムアウト**: 本番環境ではCloud Run Jobsのタイムアウトを1800秒（30分）に設定

## 9. 実装済みの機能

- ✅ **並列処理**: 複数ワーカーによる負荷分散（replicas: 3）
- ✅ **長時間処理対応**: ACK期限自動延長（AckLeaseExtender）
- ✅ **信頼性向上**: 失敗時のリトライなしで無限ループ防止

## 10. 今後の拡張

- **実際のPDF解析**: PyPDF2やpdfplumber、LLM APIを使用した本格的な解析
- **デッドレターキュー**: 完全に処理できないメッセージの隔離（現状はリトライなしで対応）
- **優先度キュー**: 緊急ジョブの優先処理
- **メトリクス収集**: 処理時間、成功率などの監視
