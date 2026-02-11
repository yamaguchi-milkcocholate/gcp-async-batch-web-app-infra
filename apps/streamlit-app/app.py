"""Streamlit フロントエンドアプリケーション.

PDF一括解析システムのメインUIアプリケーション。
ユーザーからのPDFファイルアップロードを受け付け、非同期バッチ処理をトリガーし、
処理状況をリアルタイムに表示し、完了後に結果ファイルのダウンロードを提供する。
"""

import json
import time
import uuid
from datetime import UTC, datetime

import redis
import streamlit as st
from loguru import logger

from config import Settings
from pubsub_client import PubSubClient
from storage import get_storage_client

# 設定読み込み
settings = Settings()
storage_client = get_storage_client(settings)

# Redisクライアント初期化
redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    decode_responses=True,
)

# Pub/Subクライアント初期化
if not settings.gcp_project_id:
    st.error("GCP_PROJECT_ID が設定されていません。環境変数を確認してください。")
    st.stop()

pubsub_client = PubSubClient(settings.gcp_project_id, settings.pubsub_topic)

# ページ設定
st.set_page_config(
    page_title="PDF一括解析システム",
    page_icon="📄",
    layout="centered",
)

st.title("📄 PDF一括解析システム")
st.markdown("PDFファイルをアップロードして、AI による一括解析を実行できます。")

# ファイルアップローダー
uploaded_file = st.file_uploader(
    "PDFファイルを選択してください",
    type=["pdf"],
    help="最大100MBまでのPDFファイルをアップロードできます。",
)

if uploaded_file is not None:
    # ファイル情報表示
    st.info(
        f"📁 選択されたファイル: {uploaded_file.name} ({uploaded_file.size / 1024 / 1024:.2f} MB)"
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

            # セッションステートに保存
            st.session_state["job_id"] = job_id
            st.success(f"✅ 処理を開始しました（Job ID: `{job_id}`）")

        except Exception as e:
            logger.error(f"Error starting job: {e}")
            st.error(f"❌ エラーが発生しました: {e}")

# ステータス監視
if "job_id" in st.session_state:
    job_id = st.session_state["job_id"]

    st.divider()
    st.subheader("📊 処理ステータス")

    try:
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
                st.info("⏳ 処理待機中...")
            elif status == "processing":
                st.info(f"⚙️ 処理中: {message}")
                st.progress(progress / 100, text=f"{progress}% 完了")
            elif status == "completed":
                st.success("✅ 処理完了！")
                if result_url:
                    # 結果ファイルダウンロード
                    try:
                        result_bytes = storage_client.download_file(result_url)
                        st.download_button(
                            label="📥 結果をダウンロード",
                            data=result_bytes,
                            file_name=f"result_{job_id}.md",
                            mime="text/markdown",
                        )
                    except Exception as e:
                        logger.error(f"Error downloading result: {e}")
                        st.error(f"結果ファイルのダウンロードに失敗しました: {e}")
            elif status == "error":
                st.error(f"❌ エラーが発生しました: {error_msg}")
            else:
                st.warning(f"⚠️ 不明なステータス: {status}")

            # 処理中の場合は2秒後に再読み込み
            if status in ["pending", "processing"]:
                time.sleep(2)
                st.rerun()
        else:
            st.warning("⚠️ ジョブステータスが見つかりません。処理が開始されるまでお待ちください...")
            # ステータスが見つからない場合も再読み込み（処理開始前の可能性）
            time.sleep(2)
            st.rerun()

    except redis.RedisError as e:
        logger.error(f"Redis connection error: {e}")
        st.error("❌ ステータス取得エラー: Redis接続に失敗しました")
    except Exception as e:
        logger.error(f"Error fetching job status: {e}")
        st.error(f"❌ ステータス取得エラー: {e}")
