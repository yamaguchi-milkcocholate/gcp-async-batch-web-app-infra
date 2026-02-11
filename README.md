# gcp-async-batch-web-app-infra

非同期処理を実行できるアプリのインフラ

## プロジェクト概要

GCPを使用した非同期バッチ処理Webアプリケーション。PDF一括解析システムを対象に、Streamlit フロントエンド、Cloud Run バッチワーカー、Pub/Sub、Redis、Cloud Storage を組み合わせた長時間処理可能なアーキテクチャを構築する。

## クイックスタート（ローカル開発）

### 前提条件

- Docker & Docker Compose
- Python 3.12+（オプション）

### ローカル環境での起動

```bash
# Docker Compose で全サービスを起動
docker-compose up --build

# ブラウザで http://localhost:8501 にアクセス
```

### 環境変数設定

`apps/streamlit-app/.env` ファイルを作成（`.env.example` をコピー）:

```bash
cp apps/streamlit-app/.env.example apps/streamlit-app/.env
```

## アーキテクチャ

詳細は `docs/` ディレクトリを参照してください。

- `docs/01_guidelines/` - 開発ガイドライン
- `docs/02_architecture/` - アーキテクチャ設計
- `docs/03_specs/` - 各機能の詳細仕様
