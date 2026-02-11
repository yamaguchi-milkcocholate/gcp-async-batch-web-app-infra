# 開発環境・共通基盤利用ルール

## 1. ローカル開発環境 (Docker Compose)

本プロジェクトでは、GCPの各コンポーネントをローカルでシミュレートし、開発効率を最大化するために Docker Compose を使用します。

- **Streamlit (Frontend)**: `localhost:8501` で起動。コード変更を即時反映（Hot Reload）させる。
- **Redis**: ステータス管理用。`redis:7-alpine` を使用し、データ永続化は原則オフ。
- **Pub/Sub Emulator**: `gcr.io/google.com/cloudsdktool/cloud-sdk:emulators` を使用。
- `PUBSUB_EMULATOR_HOST=localhost:8085` を環境変数に設定して接続する。

- **Local Storage**: `./local_storage` ディレクトリをバケットとしてマウント。`STORAGE_TYPE=LOCAL` で抽象化レイヤーを介して操作する。

## 2. GCPコンポーネント設定

本番環境（GCP）へのデプロイおよび設定に関するルールです。

- **Cloud Run / Cloud Run Jobs**:
- バッチ処理のタイムアウト時間は **1800秒 (30分)** 以上に設定する。
- CPU/メモリはPDF解析の負荷に応じて適切に割り当てる（例：2GiB以上）。

- **Cloud Storage (GCS)**:
- バケットには **Lifecycle Management Rule** を設定し、`Age: 1`（1日経過）で自動削除されるように構成する。

- **Cloud Memorystore (Redis)**:
- 容量はステータス管理のみのため最小サイズで構成。

- **Identity-Aware Proxy (IAP)**:
- 顧客の部署管理を容易にするため、Google Workspace アカウントによる認証をフロントエンドに付与する。

## 3. インフラ管理 (Terraform)

GCPのリソース管理はすべて Terraform で行い、手動設定を禁止します。

- **State管理**: 本番環境では Cloud Storage をバックエンドとして State ファイルを共有する。
- **モジュール化**: `Cloud Run`, `Pub/Sub`, `Redis`, `GCS` などのコンポーネントはモジュールとして定義し、再利用性を高める。
- **環境分離**: `environments/dev` や `environments/prod` ディレクトリで変数を分ける、もしくは `tfvars` を活用して環境を切り替える。
- **TTL設定**: GCSのライフサイクルルール（24時間削除）などは、必ず Terraform の `lifecycle_rule` ブロック内で定義する。
