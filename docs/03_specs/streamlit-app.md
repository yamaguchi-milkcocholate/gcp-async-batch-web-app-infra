# Spec: Streamlit Frontend Application

## 1. 概要

PDF一括解析バッチ処理システムのフロントエンドアプリケーション。ユーザーからのPDFファイルアップロードを受け付け、非同期バッチ処理をトリガーし、処理状況をリアルタイムに表示し、完了後に結果ファイルのダウンロードを提供する。

## 2. 変更の目的

- **ユーザーインターフェース**: シンプルで直感的なPDFアップロードと進捗監視のUI
- **非同期処理の起点**: Pub/Subへのメッセージ発行による処理開始
- **リアルタイムフィードバック**: Redisポーリングによる処理ステータスと進捗率の可視化
- **結果配信**: 処理完了後の統合マークダウンファイルのダウンロード提供

## 3. 技術スタック

- **Framework**: Streamlit (最新安定版)
- **言語**: Python 3.12+
- **パッケージ管理**: `uv`
- **依存ライブラリ**:
  - `streamlit`: UIフレームワーク
  - `redis`: Redisクライアント（ステータス取得）
  - `google-cloud-pubsub`: Pub/Subクライアント（メッセージ発行）
  - `google-cloud-storage`: GCSクライアント（ファイルアップロード・ダウンロード）
  - `pydantic-settings`: 環境変数管理
  - `loguru`: 構造化ログ出力

## 4. 機能要件

### 4.1. PDFファイルアップロード

- Streamlitの `st.file_uploader` を使用
- **対応形式**: PDFファイルのみ（`.pdf`）
- **ファイルサイズ制限**: 最大100MB（Streamlit デフォルト設定で調整可能）
- **アップロード先**:
  - ローカル環境（`STORAGE_TYPE=LOCAL`）: `./local_storage/uploads/{job_id}/{filename}`
  - 本番環境（`STORAGE_TYPE=GCP`）: `gs://{bucket_name}/uploads/{job_id}/{filename}`

### 4.2. ジョブID生成

- アップロード時に一意なジョブIDを生成: `uuid.uuid4()` を使用
- 形式: `{uuid}` （例: `f47ac10b-58cc-4372-a567-0e02b2c3d479`）

### 4.3. Pub/Subメッセージ発行

アップロード完了後、以下の情報をPub/Subトピックに発行:

```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "pdf_path": "uploads/f47ac10b-58cc-4372-a567-0e02b2c3d479/document.pdf",
  "bucket_name": "my-bucket",
  "timestamp": "2026-02-12T06:30:00Z"
}
```

- **トピック名**: 環境変数 `PUBSUB_TOPIC` で指定（例: `pdf-processing-topic`）
- **環境切り替え**:
  - ローカル環境: `PUBSUB_EMULATOR_HOST=localhost:8085` 経由
  - 本番環境: 実際のCloud Pub/Sub

### 4.4. 処理ステータス表示

#### Redisポーリング

- **ポーリング間隔**: 2秒
- **キー形式**: `job:{job_id}`
- **取得データ**:

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

#### UI表示要件

- **ステータス表示**: `st.status()` または `st.info()` でステータスメッセージを表示
  - `pending`: "処理待機中..."
  - `processing`: "処理中: {message}" + プログレスバー
  - `completed`: "処理完了！"
  - `error`: "エラーが発生しました: {error_msg}"

- **プログレスバー**: `st.progress(progress / 100)` でパーセンテージ表示

- **自動更新**: `st.rerun()` を使用して2秒ごとにUIを更新

### 4.5. 結果ファイルダウンロード

- **条件**: `status == "completed"` かつ `result_url` が存在する場合
- **実装**:
  - ローカル環境: `result_url` のパスから直接ファイル読み込み
  - 本番環境: GCSから `result_url` のファイルを取得
- **UI**: `st.download_button()` で統合マークダウンファイル（`.md`）をダウンロード提供

## 5. Docker構成

### 5.1. ディレクトリ構造

```
apps/
└── streamlit-app/
    ├── Dockerfile
    ├── pyproject.toml
    ├── app.py
    ├── config.py
    ├── storage.py
    └── pubsub_client.py
```

### 5.2. Dockerfile仕様

- **ベースイメージ**: `python:3.12-slim`
- **作業ディレクトリ**: `/app`
- **パッケージインストール**: `uv` を使用
- **エントリーポイント**: `streamlit run app.py --server.port=8501 --server.address=0.0.0.0`
- **Hot Reload対応**: ローカル開発時はソースコードをボリュームマウント

### 5.3. 環境変数

| 変数名                 | 説明                                 | デフォルト値           | 例                                          |
| ---------------------- | ------------------------------------ | ---------------------- | ------------------------------------------- |
| `STORAGE_TYPE`         | ストレージタイプ（`LOCAL` or `GCP`） | `LOCAL`                | `GCP`                                       |
| `LOCAL_STORAGE_PATH`   | ローカルストレージのパス             | `./local_storage`      | `/data`                                     |
| `GCS_BUCKET_NAME`      | GCSバケット名                        | -                      | `pdf-processing-bucket`                     |
| `REDIS_HOST`           | Redisホスト                          | `localhost`            | `redis`                                     |
| `REDIS_PORT`           | Redisポート                          | `6379`                 | `6379`                                      |
| `REDIS_DB`             | Redis DB番号                         | `0`                    | `0`                                         |
| `PUBSUB_EMULATOR_HOST` | Pub/Subエミュレータホスト            | -                      | `localhost:8085`                            |
| `PUBSUB_TOPIC`         | Pub/Subトピック名                    | `pdf-processing-topic` | `projects/my-project/topics/pdf-processing` |
| `GCP_PROJECT_ID`       | GCPプロジェクトID                    | -                      | `my-gcp-project`                            |

### 5.4. Docker Compose設定

```yaml
services:
  app:
    build:
      context: ./apps/streamlit-app
      dockerfile: Dockerfile
    ports:
      - "8501:8501"
    volumes:
      - ./apps/streamlit-app:/app
      - ./local_storage:/app/local_storage
    environment:
      - STORAGE_TYPE=LOCAL
      - LOCAL_STORAGE_PATH=./local_storage
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - PUBSUB_EMULATOR_HOST=pubsub:8085
      - PUBSUB_TOPIC=pdf-processing-topic
      - GCP_PROJECT_ID=local-dev
    depends_on:
      - redis
      - pubsub
```

## 6. コード設計

### 6.1. モジュール構成

#### `config.py` - 設定管理

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    storage_type: str = "LOCAL"
    local_storage_path: str = "./local_storage"
    gcs_bucket_name: str | None = None
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    pubsub_emulator_host: str | None = None
    pubsub_topic: str = "pdf-processing-topic"
    gcp_project_id: str | None = None

    class Config:
        env_file = ".env"
```

#### `storage.py` - ストレージ抽象化レイヤー

```python
from abc import ABC, abstractmethod
from pathlib import Path

class StorageClient(ABC):
    @abstractmethod
    def upload_file(self, file_bytes: bytes, destination_path: str) -> str:
        """ファイルをアップロードし、パスを返す"""
        pass

    @abstractmethod
    def download_file(self, source_path: str) -> bytes:
        """ファイルをダウンロードし、バイトデータを返す"""
        pass

class LocalStorageClient(StorageClient):
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)

    def upload_file(self, file_bytes: bytes, destination_path: str) -> str:
        # shutil を使用してローカルファイルシステムに保存
        pass

    def download_file(self, source_path: str) -> bytes:
        # ローカルファイルシステムから読み込み
        pass

class GCSStorageClient(StorageClient):
    def __init__(self, bucket_name: str):
        from google.cloud import storage
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def upload_file(self, file_bytes: bytes, destination_path: str) -> str:
        # GCSにアップロード
        pass

    def download_file(self, source_path: str) -> bytes:
        # GCSからダウンロード
        pass

def get_storage_client(settings: Settings) -> StorageClient:
    if settings.storage_type == "LOCAL":
        return LocalStorageClient(settings.local_storage_path)
    elif settings.storage_type == "GCP":
        return GCSStorageClient(settings.gcs_bucket_name)
    else:
        raise ValueError(f"Unknown storage type: {settings.storage_type}")
```

#### `pubsub_client.py` - Pub/Subクライアント

```python
import json
from google.cloud import pubsub_v1
from loguru import logger

class PubSubClient:
    def __init__(self, project_id: str, topic_name: str):
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(project_id, topic_name)

    def publish_message(self, message: dict) -> str:
        """メッセージを発行し、メッセージIDを返す"""
        message_bytes = json.dumps(message).encode("utf-8")
        future = self.publisher.publish(self.topic_path, message_bytes)
        message_id = future.result()
        logger.info(f"Published message {message_id}: {message}")
        return message_id
```

#### `app.py` - メインアプリケーション

```python
import streamlit as st
import redis
import uuid
import time
import json
from datetime import datetime
from loguru import logger
from config import Settings
from storage import get_storage_client
from pubsub_client import PubSubClient

# 設定読み込み
settings = Settings()
storage_client = get_storage_client(settings)
redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    decode_responses=True
)
pubsub_client = PubSubClient(settings.gcp_project_id, settings.pubsub_topic)

st.title("PDF一括解析システム")

# ファイルアップローダー
uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])

if uploaded_file is not None:
    if st.button("解析開始"):
        # ジョブID生成
        job_id = str(uuid.uuid4())

        # ファイルアップロード
        destination_path = f"uploads/{job_id}/{uploaded_file.name}"
        file_bytes = uploaded_file.read()
        storage_client.upload_file(file_bytes, destination_path)

        # Pub/Subメッセージ発行
        message = {
            "job_id": job_id,
            "pdf_path": destination_path,
            "bucket_name": settings.gcs_bucket_name or "local",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        pubsub_client.publish_message(message)

        # セッションステートに保存
        st.session_state["job_id"] = job_id
        st.success(f"処理を開始しました（Job ID: {job_id}）")

# ステータス監視
if "job_id" in st.session_state:
    job_id = st.session_state["job_id"]

    # Redisからステータス取得
    job_key = f"job:{job_id}"
    job_data_str = redis_client.get(job_key)

    if job_data_str:
        job_data = json.loads(job_data_str)
        status = job_data.get("status", "unknown")
        progress = job_data.get("progress", 0)
        message = job_data.get("message", "")
        error_msg = job_data.get("error_msg", "")
        result_url = job_data.get("result_url", "")

        # ステータス表示
        if status == "pending":
            st.info("処理待機中...")
        elif status == "processing":
            st.info(f"処理中: {message}")
            st.progress(progress / 100)
        elif status == "completed":
            st.success("処理完了！")
            if result_url:
                # 結果ファイルダウンロード
                result_bytes = storage_client.download_file(result_url)
                st.download_button(
                    label="結果をダウンロード",
                    data=result_bytes,
                    file_name=f"result_{job_id}.md",
                    mime="text/markdown"
                )
        elif status == "error":
            st.error(f"エラーが発生しました: {error_msg}")

        # 処理中の場合は2秒後に再読み込み
        if status in ["pending", "processing"]:
            time.sleep(2)
            st.rerun()
    else:
        st.warning("ジョブステータスが見つかりません")
```

## 7. テスト方法

### 7.1. ローカル開発環境での動作確認

1. Docker Composeで全サービス起動:

   ```bash
   docker-compose up
   ```

2. ブラウザで `http://localhost:8501` にアクセス

3. PDFファイルをアップロードし、「解析開始」ボタンをクリック

4. 進捗表示が更新されることを確認（Redisにモックデータを手動投入して確認）

5. 処理完了後、ダウンロードボタンが表示されることを確認

### 7.2. Redisモックデータ投入

```bash
docker exec -it redis redis-cli
SET job:test-job-id '{"status":"processing","progress":50,"message":"Page 5/10 analyzing...","result_url":"","error_msg":"","updated_at":"2026-02-12T06:40:00Z"}'
```

## 8. 非機能要件

- **レスポンシブデザイン**: Streamlitのデフォルトレイアウトで対応
- **エラーハンドリング**:
  - ファイルアップロード失敗時のリトライまたはエラー表示
  - Redis接続エラー時の適切なメッセージ表示
  - Pub/Sub発行失敗時のエラーハンドリング
- **ログ出力**: `loguru` で構造化ログを出力（INFO, ERROR レベル）
- **セキュリティ**: 本番環境ではIAPによる認証を付与（インフラ側で設定）

## 9. 今後の拡張

- **複数ファイル対応**: 一度に複数PDFをアップロード
- **履歴表示**: 過去のジョブ一覧と結果ダウンロード
- **キャンセル機能**: 処理中ジョブのキャンセル
- **通知機能**: 処理完了時のメール通知
