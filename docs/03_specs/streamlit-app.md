# Spec: Streamlit Frontend Application

## 1. 概要

PDF一括解析バッチ処理システムのフロントエンドアプリケーション。ユーザーからのPDFファイルアップロードを受け付け、非同期バッチ処理をトリガーし、処理状況をリアルタイムに表示し、完了後に結果ファイルのダウンロードを提供する。

## 2. 変更の目的

- **ユーザーインターフェース**: 3タブ構成(ジョブ登録/ジョブ一覧/ステータス確認)による直感的なUI
- **非同期処理の起点**: Pub/Subへのメッセージ発行による処理開始
- **ジョブ履歴管理**: 過去24時間のジョブ一覧表示とステータス確認
- **リアルタイムフィードバック**: Redisポーリングによる処理ステータスと進捗率の可視化
- **結果配信**: 処理完了後の統合マークダウンファイルのダウンロード提供
- **リロード耐性**: ブラウザリロード後もジョブ一覧から処理中のジョブを追跡可能

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

### 4.1. UI構成（3タブ）

#### タブ1: 📤 ジョブ登録

PDFファイルのアップロードとジョブ登録を行う。

- Streamlitの `st.file_uploader` を使用
- **対応形式**: PDFファイルのみ（`.pdf`）
- **ファイルサイズ制限**: 最大100MB（Streamlit デフォルト設定で調整可能）
- **アップロード先**:
  - ローカル環境（`STORAGE_TYPE=LOCAL`）: `./local_storage/uploads/{job_id}/{filename}`
  - 本番環境（`STORAGE_TYPE=GCP`）: `gs://{bucket_name}/uploads/{job_id}/{filename}`

**処理フロー:**
1. ジョブID生成: `uuid.uuid4()` を使用（例: `f47ac10b-58cc-4372-a567-0e02b2c3d479`）
2. ファイルをストレージにアップロード
3. Pub/Subメッセージ発行（処理開始トリガー）
4. 成功メッセージ表示（Job IDを含む）

**Pub/Subメッセージ形式:**

```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "pdf_path": "uploads/f47ac10b-58cc-4372-a567-0e02b2c3d479/document.pdf",
  "bucket_name": "my-bucket",
  "timestamp": "2026-02-12T06:30:00Z"
}
```

- **トピック名**: 環境変数 `PUBSUB_TOPIC` で指定（例: `pdf-processing-topic`）

#### タブ2: 📋 ジョブ一覧

過去24時間に登録された全ジョブを一覧表示する。

**取得方法:**
- Redis SCAN コマンドで `job:*` パターンのキーを全て取得
- 各キーから `updated_at` を取得し、降順ソート（新しい順）

**一覧表示項目:**

| 項目 | 内容 | 例 |
|------|------|-----|
| Job ID | ジョブ識別子（先頭8文字） | `f47ac10b` |
| ステータス | `pending`, `processing`, `completed`, `failed` | 🟡 処理中 |
| 進捗 | 進捗率（%） | 45% |
| 更新日時 | 最終更新時刻 | 2026-02-12 06:35:00 |
| アクション | 「詳細を見る」ボタン | ボタンクリックで選択 |

**実装詳細:**
```python
# Redis SCAN でジョブ一覧取得
cursor = 0
jobs = []
while True:
    cursor, keys = redis_client.scan(cursor, match="job:*", count=100)
    for key in keys:
        job_data_str = redis_client.get(key)
        if job_data_str:
            job_data = json.loads(job_data_str)
            job_data["job_id"] = key.replace("job:", "")
            jobs.append(job_data)
    if cursor == 0:
        break

# updated_at でソート（新しい順）
jobs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
```

**UI要件:**
- ステータスに応じたアイコン表示:
  - `pending`: 🟡 待機中
  - `processing`: 🔵 処理中
  - `completed`: 🟢 完了
  - `failed`: 🔴 失敗
- 「詳細を見る」ボタンクリックで `st.session_state["selected_job_id"]` に保存

#### タブ3: 📊 ステータス確認

選択したジョブの詳細ステータスを表示し、完了時にダウンロードを提供する。

**前提条件:**
- タブ2で「詳細を見る」ボタンをクリックしたジョブ、または直近で登録したジョブ

**表示内容:**
- **ジョブID**: `st.code()` でフルIDを表示
- **ステータス**: 現在の処理状態
- **進捗バー**: `st.progress()` で進捗率を可視化
- **メッセージ**: 現在の処理メッセージ（例: "Page 5/12 analyzing..."）
- **更新日時**: 最終更新時刻
- **エラーメッセージ**: 失敗時のみ表示

**Redisデータ形式:**

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

- **キー形式**: `job:{job_id}`
- **TTL**: 24時間（86400秒）- ワーカー側で設定

**ステータス別UI表示:**

| status | 表示 | 動作 |
|--------|------|------|
| `pending` | 🟡 処理待機中... | 2秒後に自動リロード |
| `processing` | 🔵 処理中: {message}<br>プログレスバー | 2秒後に自動リロード |
| `completed` | 🟢 処理完了！<br>ダウンロードボタン | リロードなし |
| `failed` | 🔴 エラー: {error_msg} | リロードなし |

**自動更新:**
- `status` が `pending` または `processing` の場合、2秒後に `st.rerun()` で自動更新

### 4.2. 結果ファイルダウンロード

- **条件**: `status == "completed"` かつ `result_url` が存在する場合
- **実装**:
  - ローカル環境: `result_url` のパスから直接ファイル読み込み
  - 本番環境: GCSから `result_url` のファイルを取得
- **UI**: `st.download_button()` で結果ファイル（`.json` または `.md`）をダウンロード提供

### 4.3. データ永続性とリロード耐性

**問題点（旧実装）:**
- `st.session_state` のみにジョブIDを保存
- ブラウザリロード時にセッションステートがクリアされ、処理中のジョブを追跡不可

**解決策（新実装）:**
- Redis SCAN で過去24時間の全ジョブを取得可能
- ジョブ一覧から任意のジョブを選択して追跡可能
- リロード後もジョブ一覧から処理中のジョブを再選択できる

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

#### `app.py` - メインアプリケーション（3タブ構成）

```python
import streamlit as st
import redis
import uuid
import time
import json
from datetime import datetime, UTC
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

# ページ設定
st.set_page_config(
    page_title="PDF一括解析システム",
    page_icon="📄",
    layout="wide",
)

st.title("📄 PDF一括解析システム")

# 3タブ構成
tab1, tab2, tab3 = st.tabs(["📤 ジョブ登録", "📋 ジョブ一覧", "📊 ステータス確認"])

# ========================================
# タブ1: ジョブ登録
# ========================================
with tab1:
    st.header("PDFファイルをアップロード")

    uploaded_file = st.file_uploader(
        "PDFファイルを選択してください",
        type=["pdf"],
        help="最大100MBまでのPDFファイルをアップロードできます。",
    )

    if uploaded_file is not None:
        st.info(
            f"📁 選択されたファイル: {uploaded_file.name} "
            f"({uploaded_file.size / 1024 / 1024:.2f} MB)"
        )

        if st.button("🚀 解析開始", type="primary"):
            try:
                # ジョブID生成
                job_id = str(uuid.uuid4())
                logger.info(f"Starting job {job_id} for file {uploaded_file.name}")

                # ファイルアップロード
                destination_path = f"uploads/{job_id}/{uploaded_file.name}"
                file_bytes = uploaded_file.read()
                storage_client.upload_file(file_bytes, destination_path)
                logger.info(f"File uploaded: {destination_path}")

                # Pub/Subメッセージ発行
                message = {
                    "job_id": job_id,
                    "pdf_path": destination_path,
                    "bucket_name": settings.gcs_bucket_name or "local",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                message_id = pubsub_client.publish_message(message)
                logger.info(f"Published Pub/Sub message: {message_id}")

                # セッションステートに保存（ステータス確認タブで使用）
                st.session_state["selected_job_id"] = job_id

                st.success(
                    f"✅ 処理を開始しました\n\n"
                    f"**Job ID**: `{job_id}`\n\n"
                    f"「ステータス確認」タブで進捗を確認できます。"
                )

            except Exception as e:
                logger.error(f"Error starting job: {e}")
                st.error(f"❌ エラーが発生しました: {e}")

# ========================================
# タブ2: ジョブ一覧
# ========================================
with tab2:
    st.header("過去24時間のジョブ一覧")

    try:
        # Redis SCAN でjob:*パターンのキーを全て取得
        cursor = 0
        jobs = []
        while True:
            cursor, keys = redis_client.scan(cursor, match="job:*", count=100)
            for key in keys:
                job_data_str = redis_client.get(key)
                if job_data_str:
                    job_data = json.loads(job_data_str)
                    job_data["job_id"] = key.replace("job:", "")
                    jobs.append(job_data)
            if cursor == 0:
                break

        if not jobs:
            st.info("ジョブが見つかりませんでした。")
        else:
            # updated_at でソート（新しい順）
            jobs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

            # テーブル表示
            for job in jobs:
                job_id = job.get("job_id", "unknown")
                status = job.get("status", "unknown")
                progress = job.get("progress", 0)
                updated_at = job.get("updated_at", "")

                # ステータスアイコン
                status_icons = {
                    "pending": "🟡",
                    "processing": "🔵",
                    "completed": "🟢",
                    "failed": "🔴",
                }
                icon = status_icons.get(status, "⚪")

                # 行表示
                col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 2, 1])
                with col1:
                    st.text(f"{job_id[:8]}...")
                with col2:
                    st.text(f"{icon} {status}")
                with col3:
                    st.text(f"{progress}%")
                with col4:
                    st.text(updated_at[:19] if updated_at else "")
                with col5:
                    if st.button("詳細", key=f"select_{job_id}"):
                        st.session_state["selected_job_id"] = job_id
                        st.success(f"ジョブ `{job_id[:8]}...` を選択しました")
                        st.rerun()

    except redis.RedisError as e:
        logger.error(f"Redis connection error: {e}")
        st.error("❌ Redis接続エラー")
    except Exception as e:
        logger.error(f"Error fetching job list: {e}")
        st.error(f"❌ ジョブ一覧の取得に失敗しました: {e}")

# ========================================
# タブ3: ステータス確認
# ========================================
with tab3:
    st.header("ジョブのステータス確認")

    # 選択されたジョブIDを取得
    selected_job_id = st.session_state.get("selected_job_id")

    if not selected_job_id:
        st.warning("⚠️ ジョブが選択されていません。「ジョブ一覧」タブからジョブを選択してください。")
    else:
        st.subheader(f"Job ID: `{selected_job_id}`")

        try:
            # Redisからステータス取得
            job_key = f"job:{selected_job_id}"
            job_data_str = redis_client.get(job_key)

            if not job_data_str:
                st.warning(
                    "⚠️ ジョブステータスが見つかりません。\n\n"
                    "- 処理が開始されていない可能性があります\n"
                    "- 24時間以上経過してデータが削除された可能性があります"
                )
            else:
                job_data = json.loads(job_data_str)
                status = job_data.get("status", "unknown")
                progress = job_data.get("progress", 0)
                message = job_data.get("message", "")
                error_msg = job_data.get("error_msg", "")
                result_url = job_data.get("result_url", "")
                updated_at = job_data.get("updated_at", "")

                # ステータス表示
                if status == "pending":
                    st.info("🟡 処理待機中...")
                    st.text(f"更新日時: {updated_at}")
                    time.sleep(2)
                    st.rerun()

                elif status == "processing":
                    st.info(f"🔵 処理中: {message}")
                    st.progress(progress / 100, text=f"{progress}% 完了")
                    st.text(f"更新日時: {updated_at}")
                    time.sleep(2)
                    st.rerun()

                elif status == "completed":
                    st.success("🟢 処理完了！")
                    st.text(f"更新日時: {updated_at}")

                    if result_url:
                        try:
                            result_bytes = storage_client.download_file(result_url)
                            st.download_button(
                                label="📥 結果をダウンロード",
                                data=result_bytes,
                                file_name=f"result_{selected_job_id}.json",
                                mime="application/json",
                            )
                        except Exception as e:
                            logger.error(f"Error downloading result: {e}")
                            st.error(f"結果ファイルのダウンロードに失敗しました: {e}")
                    else:
                        st.warning("結果URLが設定されていません")

                elif status == "failed":
                    st.error(f"🔴 エラーが発生しました")
                    st.error(f"**エラー内容**: {error_msg}")
                    st.text(f"更新日時: {updated_at}")

                else:
                    st.warning(f"⚠️ 不明なステータス: {status}")

        except redis.RedisError as e:
            logger.error(f"Redis connection error: {e}")
            st.error("❌ Redis接続エラー")
        except Exception as e:
            logger.error(f"Error fetching job status: {e}")
            st.error(f"❌ ステータス取得エラー: {e}")
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

## 9. 実装済み機能

- ✅ **3タブUI構成**: ジョブ登録/一覧/ステータス確認の分離
- ✅ **ジョブ履歴表示**: 過去24時間のジョブ一覧（Redis SCAN）
- ✅ **リロード耐性**: ブラウザリロード後もジョブ追跡可能
- ✅ **24時間TTL**: 古いジョブデータの自動削除

## 10. 今後の拡張

- **複数ファイル対応**: 一度に複数PDFをアップロード
- **ジョブ検索・フィルタ**: ステータス別フィルタ、ジョブID検索
- **キャンセル機能**: 処理中ジョブのキャンセル
- **通知機能**: 処理完了時のメール通知
- **ページネーション**: ジョブ一覧の大量データ対応
