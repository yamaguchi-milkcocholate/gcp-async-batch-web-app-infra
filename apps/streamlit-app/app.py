"""Streamlit フロントエンドアプリケーション.

PDF一括解析システムのメインUIアプリケーション。
ユーザーからのPDFファイルアップロードを受け付け、非同期バッチ処理をトリガーし、
処理状況をリアルタイムに表示し、完了後に結果ファイルのダウンロードを提供する。

3タブ構成:
- タブ1: ジョブ登録 - PDFアップロードとジョブ開始
- タブ2: ジョブ一覧 - 過去24時間のジョブ履歴表示
- タブ3: ステータス確認 - 選択ジョブの詳細表示
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
                    f"「ジョブ一覧」タブで確認できます。"
                )

                # 画面を再描画してジョブ一覧を更新
                time.sleep(1)
                st.rerun()

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

            # ヘッダー行
            col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 2, 1])
            with col1:
                st.markdown("**Job ID**")
            with col2:
                st.markdown("**ステータス**")
            with col3:
                st.markdown("**進捗**")
            with col4:
                st.markdown("**更新日時**")
            with col5:
                st.markdown("**操作**")

            st.divider()

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
                    st.text(f"{job_id}")
                with col2:
                    st.text(f"{icon} {status}")
                with col3:
                    st.text(f"{progress}%")
                with col4:
                    st.text(updated_at[:19] if updated_at else "")
                with col5:
                    if st.button("詳細", key=f"select_{job_id}"):
                        st.session_state["selected_job_id"] = job_id
                        st.toast(
                            f"ジョブ `{job_id}` を選択しました。ステータスで確認できます",
                            icon=":material/output:",
                        )

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
                    st.error("🔴 エラーが発生しました")
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
