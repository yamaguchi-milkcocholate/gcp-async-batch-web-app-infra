# Spec: GCP環境へのTerraformデプロイ

**最終更新**: 2026-02-13（実際のデプロイ結果を反映）

## 1. 概要

PDF一括解析バッチ処理システムのGCP本番環境を、Terraformを使用して完全自動構築する。ローカルDocker Compose環境で動作確認済みのアプリケーションを、Cloud Run (Frontend)、Cloud Run Service (Batch Worker - Push型)、Cloud Pub/Sub、Cloud Memorystore for Redis、Cloud Storageで構成されたインフラストラクチャにデプロイする。

### 重要な変更点（実際のデプロイから得られた知見）

1. **Terraform Version**: 1.10.0 → 1.9.0以上に変更（互換性確保）
2. **VPC Connector**: 名前は24文字以内、min_instances=2が必須（GCP制約）
3. **Dockerアーキテクチャ**: AMD64でビルド必須（`--platform linux/amd64`）
4. **Pub/Sub認証**: batch-worker-saをOIDC認証に使用（iam.serviceAccounts.actAs問題回避）
5. **IAM自動化**: Secret Manager・GCSのIAM権限をTerraformモジュールに含め、手動設定を廃止
6. **Push型実装**: Cloud Run Service（Flask/Gunicorn）でHTTP POSTを受信

これらの変更により、**terraform apply一回で全リソースとIAM権限が完全に自動構築**されます。

## 2. 変更の目的

- **Infrastructure as Code**: 全てのGCPリソースをTerraformで管理し、手動設定を排除
- **自動構築**: `terraform apply` 一回で本番環境を構築可能にする
- **セキュリティ**: サービスアカウントと最小権限の原則に基づいたIAMロール設定
- **運用性**: 構築手順の標準化と引き継ぎドキュメントの整備
- **コスト管理**: GCSライフサイクルルールによる自動データ削除（24時間TTL）

## 3. 技術スタック

### 3.1. GCPサービス

| サービス                      | 用途                     | 重要設定                                        |
| ----------------------------- | ------------------------ | ----------------------------------------------- |
| **Cloud Run**                 | Streamlitフロントエンド  | タイムアウト300秒、メモリ512MiB、認証なし       |
| **Cloud Run**                 | PDFバッチ処理ワーカー    | タイムアウト1800秒、メモリ2GiB、Push型受信      |
| **Cloud Pub/Sub**             | 非同期メッセージキュー   | Push型配信、ACK期限600秒、メッセージ保持期間1日 |
| **Cloud Memorystore (Redis)** | ジョブステータス管理     | Basic Tier、メモリ1GB、高可用性なし             |
| **Cloud Storage**             | PDF/結果ファイル一時保管 | Lifecycle Rule: 1日で自動削除                   |
| **Secret Manager**            | Redis接続情報管理        | RedisホストIPを保存                             |

### 3.2. Terraform構成

- **バージョン**: Terraform 1.9.0以上（1.10.0以上推奨）
- **Provider**: `google` v6.18.0以上
- **State管理**: Cloud Storage バックエンド（`tfstate` バケット）
- **モジュール化**: コンポーネント別モジュール（VPC、Cloud Run、Pub/Sub、Redis、GCS）

## 4. アーキテクチャ設計

### 4.1. ネットワーク構成

```
[Internet]
    ↓ (HTTPS)
[Cloud Run: Streamlit Frontend]
    ↓ (Pub/Sub Publish)
[Cloud Pub/Sub Topic: pdf-processing-topic]
    ↓ (Push Subscription: HTTP POST)
[Cloud Run: Batch Worker Service]
    ↓ (Redis: Status Update / GCS: File I/O)
[Cloud Memorystore (Redis)] + [Cloud Storage]
```

**Push型のメリット**:

- メッセージ到着時に即座に処理開始（低レイテンシ）
- Cloud Schedulerが不要（コスト削減）
- Cloud Runの自動スケーリングでワーカー数を動的調整

#### 非同期処理アーキテクチャの説明

**重要**: Streamlitのタイムアウトは300秒（5分）ですが、30分の処理を待つことができる理由：

1. **ファイルアップロード**: ユーザーがPDFをアップロード → GCSに保存（数秒で完了）
2. **ジョブ投入**: Pub/Subトピックにメッセージを送信（即座に完了、HTTP接続終了）
3. **進捗表示**: StreamlitがRedisをポーリングして進捗をリアルタイム表示（WebSocketまたはSSEで更新）
4. **バックグラウンド処理**: Pub/SubがBatch Worker（Cloud Run Service）にHTTP POSTでメッセージを送信し、長時間処理を実行（最大30分）

つまり、**HTTPリクエストは短時間で完了**し、長時間処理は**非同期バッチ処理**で実行されます。Streamlitのタイムアウトは、単一HTTPリクエストの制限であり、バッチ処理の制限ではありません。

**Push型の動作フロー**:

- Pub/Subがメッセージを受信すると、自動的にBatch Worker（Cloud Run）のエンドポイント（`/`）にHTTP POSTを送信
- Cloud Runが起動していない場合は自動起動（コールドスタート）
- 処理完了後、200 OKを返すとPub/Subはメッセージを削除
- エラー発生時（非200レスポンス）は自動リトライ

### 4.2. VPCとサブネット

| リソース           | CIDR          | 用途                         |
| ------------------ | ------------- | ---------------------------- |
| **VPC**            | `10.0.0.0/16` | プライベートネットワーク     |
| **Subnet (Redis)** | `10.0.1.0/24` | Cloud Memorystore専用        |
| **VPC Connector**  | `10.0.2.0/28` | Cloud Run/Jobs → Redis接続用 |

**重要**: Cloud MemystoreはVPC内でのみアクセス可能なため、Serverless VPC Accessコネクタを使用してCloud Run/JobsからRedisに接続する。

### 4.3. サービスアカウントとIAMロール

#### サービスアカウント一覧

| サービスアカウント | 用途                    | 主要ロール                                                        |
| ------------------ | ----------------------- | ----------------------------------------------------------------- |
| `streamlit-sa`     | Cloud Run (Frontend)    | Pub/Sub Publisher、Storage Object Viewer/Creator、Secret Accessor |
| `batch-worker-sa`  | Cloud Run Jobs (Worker) | Pub/Sub Subscriber、Storage Object Admin、Secret Accessor         |
| `terraform-sa`     | Terraform実行用         | Editor、Service Account User、Secret Manager Admin                |

#### IAMロール詳細

**Streamlit Frontend (`streamlit-sa`)**:

- `roles/pubsub.publisher` - Pub/Subトピックへのメッセージ送信
- `roles/storage.objectViewer` - GCSからのPDFダウンロード
- `roles/storage.objectCreator` - GCSへのPDFアップロード
- `roles/secretmanager.secretAccessor` - Redis接続情報取得

**Batch Worker (`batch-worker-sa`)**:

- `roles/storage.objectAdmin` - GCS上のPDF読み取り・結果ファイル書き込み
- `roles/secretmanager.secretAccessor` - Redis接続情報取得

**注意**: Push型Pub/Subでは、`roles/pubsub.subscriber`は不要です。Pub/Subサービスアカウントがbatch-worker Cloud Runを呼び出すため、Pub/Subサービスアカウントに`roles/run.invoker`権限を付与します。

## 5. Terraformディレクトリ構造

```
terraform/
├── main.tf                    # ルートモジュール、モジュール呼び出し
├── variables.tf               # 入力変数定義
├── outputs.tf                 # 出力変数（Cloud RunのURL、GCSバケット名など）
├── terraform.tfvars           # 環境固有の変数値（本番環境設定）
├── backend.tf                 # State管理用Cloud Storageバックエンド設定
├── providers.tf               # Googleプロバイダー設定
│
├── modules/
│   ├── vpc/                   # VPC、サブネット、VPCコネクタ
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   │
│   ├── pubsub/                # Pub/Subトピックとサブスクリプション
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   │
│   ├── redis/                 # Cloud Memorystore (Redis)
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   │
│   ├── storage/               # Cloud Storage バケット + Lifecycle
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   │
│   ├── cloud-run/             # Cloud Run (Streamlit Frontend)
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── outputs.tf
│   │
│   └── cloud-run-worker/      # Cloud Run Service (Batch Worker - Push型)
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
│
│   # 注意: IAMモジュールは含まれません
│   # サービスアカウントとIAMロールは手動設定（セキュリティ重視）
│
└── scripts/
    ├── init.sh                # 初回セットアップスクリプト
    └── deploy.sh              # デプロイスクリプト
```

## 6. Terraform実装詳細

### 6.1. Backend設定 (`backend.tf`)

```hcl
terraform {
  backend "gcs" {
    bucket = "YOUR_PROJECT_ID-tfstate"  # 事前に手動作成
    prefix = "terraform/state"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.18.0"
    }
  }

  required_version = ">= 1.9.0"
}
```

### 6.2. VPCモジュール (`modules/vpc/main.tf`)

```hcl
resource "google_compute_network" "vpc" {
  name                    = var.vpc_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "redis_subnet" {
  name          = "${var.vpc_name}-redis-subnet"
  ip_cidr_range = "10.0.1.0/24"
  region        = var.region
  network       = google_compute_network.vpc.id
}

# Serverless VPC Access Connector (Cloud Run/Jobs → Redis)
resource "google_vpc_access_connector" "connector" {
  name          = "pdf-vpc-connector"  # 重要: 24文字以内、英小文字・数字・ハイフンのみ
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.0.2.0/28"

  # スループット設定
  min_instances = 2      # GCPの制約: 最低2（0は設定不可）
  max_instances = 3      # 最大インスタンス数（負荷に応じて自動スケール）
  machine_type  = "e2-micro"  # 最小インスタンスタイプ
}

# Redisへのイングレスファイアウォールルール
resource "google_compute_firewall" "redis_ingress" {
  name    = "${var.vpc_name}-allow-redis"
  network = google_compute_network.vpc.name

  allow {
    protocol = "tcp"
    ports    = ["6379"]
  }

  source_ranges = ["10.0.2.0/28"]  # VPC Connectorからのアクセスのみ許可
}
```

### 6.3. Redisモジュール (`modules/redis/main.tf`)

```hcl
# Private Service Connection（VPCピアリング）を確保
resource "google_compute_global_address" "private_ip_address" {
  name          = "${var.redis_instance_name}-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = var.vpc_id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = var.vpc_id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_address.name]
}

resource "google_redis_instance" "redis" {
  name               = var.redis_instance_name
  tier               = "BASIC"          # 本番環境ではSTANDARD推奨（高可用性）
  memory_size_gb     = 1
  region             = var.region
  authorized_network = var.vpc_id

  redis_version = "REDIS_7_0"
  display_name  = "PDF Processing Status Store"

  # セキュリティ: TLS有効化（推奨）
  transit_encryption_mode = "DISABLED"  # 開発環境用、本番ではSERVER_AUTH推奨

  labels = {
    environment = var.environment
    app         = "pdf-batch-processing"
  }

  # Private Service Connectionが確立してから作成
  depends_on = [google_service_networking_connection.private_vpc_connection]
}

# Secret Managerに接続情報を保存
resource "google_secret_manager_secret" "redis_host" {
  secret_id = "redis-host"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "redis_host_version" {
  secret      = google_secret_manager_secret.redis_host.id
  secret_data = google_redis_instance.redis.host
}

# Secret Manager IAM - Streamlit SAにアクセス権限を付与
resource "google_secret_manager_secret_iam_member" "streamlit_secret_accessor" {
  secret_id = google_secret_manager_secret.redis_host.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.streamlit_sa_email}"
}

# Secret Manager IAM - Batch Worker SAにアクセス権限を付与
resource "google_secret_manager_secret_iam_member" "batch_worker_secret_accessor" {
  secret_id = google_secret_manager_secret.redis_host.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.batch_worker_sa_email}"
}
```

**重要**: `modules/redis/variables.tf`に以下の変数を追加してください：

```hcl
variable "streamlit_sa_email" {
  description = "Streamlit service account email"
  type        = string
}

variable "batch_worker_sa_email" {
  description = "Batch Worker service account email"
  type        = string
}
```

### 6.4. Pub/Subモジュール (`modules/pubsub/main.tf`)

```hcl
resource "google_pubsub_topic" "pdf_processing" {
  name = var.topic_name

  message_retention_duration = "86400s"  # 1日間保持

  labels = {
    environment = var.environment
  }
}

resource "google_pubsub_subscription" "pdf_processing_sub" {
  name  = var.subscription_name
  topic = google_pubsub_topic.pdf_processing.id

  ack_deadline_seconds = 600  # 10分（長時間処理対応）

  message_retention_duration = "86400s"  # 1日間

  # Push設定（Cloud Run Serviceに配信）
  push_config {
    push_endpoint = var.batch_worker_url  # Cloud Run ServiceのURL

    oidc_token {
      # 重要: batch-worker-saを使用（Pub/SubサービスアカウントだとIAM権限エラーが発生）
      service_account_email = var.pubsub_service_account_email  # batch-worker-saのemailを渡す
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  # デッドレターポリシー（オプション）
  # dead_letter_policy {
  #   dead_letter_topic     = google_pubsub_topic.dead_letter.id
  #   max_delivery_attempts = 5
  # }

  labels = {
    environment = var.environment
  }
}
```

### 6.5. Cloud Storageモジュール (`modules/storage/main.tf`)

```hcl
resource "google_storage_bucket" "pdf_storage" {
  name          = var.bucket_name
  location      = var.region
  storage_class = "STANDARD"

  uniform_bucket_level_access = true

  # 24時間TTL: 1日経過したファイルを自動削除
  lifecycle_rule {
    condition {
      age = 1  # 1日
    }
    action {
      type = "Delete"
    }
  }

  # CORS設定（Streamlitからのアップロード用）
  cors {
    origin          = ["*"]
    method          = ["GET", "POST", "PUT"]
    response_header = ["Content-Type"]
    max_age_seconds = 3600
  }

  labels = {
    environment = var.environment
    purpose     = "temporary-pdf-storage"
  }
}

# GCS IAM - Streamlit SAにViewer/Creator権限を付与
resource "google_storage_bucket_iam_member" "streamlit_object_viewer" {
  bucket = google_storage_bucket.pdf_storage.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.streamlit_sa_email}"
}

resource "google_storage_bucket_iam_member" "streamlit_object_creator" {
  bucket = google_storage_bucket.pdf_storage.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${var.streamlit_sa_email}"
}

# GCS IAM - Batch Worker SAにAdmin権限を付与
resource "google_storage_bucket_iam_member" "batch_worker_object_admin" {
  bucket = google_storage_bucket.pdf_storage.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.batch_worker_sa_email}"
}
```

**重要**: `modules/storage/variables.tf`に以下の変数を追加してください：

```hcl
variable "streamlit_sa_email" {
  description = "Streamlit service account email"
  type        = string
}

variable "batch_worker_sa_email" {
  description = "Batch Worker service account email"
  type        = string
}
```

### 6.6. Cloud Runモジュール (`modules/cloud-run/main.tf`)

```hcl
resource "google_cloud_run_v2_service" "streamlit" {
  name     = var.service_name
  location = var.region

  template {
    containers {
      image = var.container_image  # "${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest"

      ports {
        container_port = 8501
      }

      env {
        name  = "STORAGE_TYPE"
        value = "GCP"
      }

      env {
        name  = "GCS_BUCKET_NAME"
        value = var.gcs_bucket_name
      }

      env {
        name  = "PUBSUB_TOPIC"
        value = var.pubsub_topic_name
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      # Redis接続情報（Secret Manager経由）
      env {
        name = "REDIS_HOST"
        value_source {
          secret_key_ref {
            secret  = var.redis_host_secret_id
            version = "latest"  # 本番運用では "1" など特定バージョンを指定推奨
          }
        }
      }

      env {
        name  = "REDIS_PORT"
        value = "6379"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    timeout         = "300s"
    service_account = var.service_account_email

    # VPC Connector経由でRedisに接続
    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# 認証なしで公開アクセス許可
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  location = google_cloud_run_v2_service.streamlit.location
  name     = google_cloud_run_v2_service.streamlit.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
```

### 6.7. Cloud Run Serviceモジュール（Batch Worker）(`modules/cloud-run-worker/main.tf`)

**重要**: Pull型からPush型に変更したため、Cloud Run Jobsの代わりにCloud Run Serviceを使用します。

```hcl
resource "google_cloud_run_v2_service" "batch_worker" {
  name     = var.service_name
  location = var.region

  template {
    containers {
      image = var.container_image  # "${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest"

      # Push型ではPOSTリクエストを受信するため、ポート設定が必要
      ports {
        container_port = 8080
      }

      env {
        name  = "STORAGE_TYPE"
        value = "GCP"
      }

      env {
        name  = "GCS_BUCKET_NAME"
        value = var.gcs_bucket_name
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name = "REDIS_HOST"
        value_source {
          secret_key_ref {
            secret  = var.redis_host_secret_id
            version = "latest"  # 本番運用では "1" など特定バージョンを指定推奨
          }
        }
      }

      env {
        name  = "REDIS_PORT"
        value = "6379"
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }
    }

    timeout         = "1800s"  # 30分
    service_account = var.service_account_email

    # VPC Connector経由でRedisに接続
    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    # スケーリング設定
    scaling {
      min_instance_count = 0  # アイドル時はインスタンス0（コスト削減）
      max_instance_count = 3  # 最大3インスタンス（並列処理）
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Batch Worker SAにCloud Run呼び出し権限を付与
# 注意: この設定はPush型Pub/Subに必須（Pub/Sub がこのSAで認証してCloud Runを呼び出す）
resource "google_cloud_run_v2_service_iam_member" "pubsub_invoker" {
  location = google_cloud_run_v2_service.batch_worker.location
  name     = google_cloud_run_v2_service.batch_worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.service_account_email}"
}
```

**重要変更点**: 当初設計ではPub/Subサービスアカウント（`service-${project_number}@gcp-sa-pubsub.iam.gserviceaccount.com`）を使用予定でしたが、実際のデプロイでは`iam.serviceAccounts.actAs`権限エラーが発生しました。回避策として、`batch-worker-sa`をOIDC認証とCloud Run invoker権限の両方で使用します。

### 6.8. サービスアカウントの参照方法（Data Sources）

**重要**: このプロジェクトでは、セキュリティ重視のため、サービスアカウントとIAMロールは**手動で作成**します（Owner権限者が実施、セクション7.1参照）。

Terraformでは、手動作成されたサービスアカウントを`data source`で参照します。

#### ルートモジュール（`main.tf`）でのdata source定義

```hcl
# 手動作成されたサービスアカウントを参照
data "google_service_account" "streamlit" {
  account_id = "streamlit-sa"
}

data "google_service_account" "batch_worker" {
  account_id = "batch-worker-sa"
}

# Cloud Runモジュールに渡す
module "cloud_run" {
  source = "./modules/cloud-run"

  service_account_email = data.google_service_account.streamlit.email
  # ... その他の変数
}

# Cloud Run Jobsモジュールに渡す
module "cloud_run_jobs" {
  source = "./modules/cloud-run-jobs"

  service_account_email = data.google_service_account.batch_worker.email
  # ... その他の変数
}
```

#### IAM設定が二段階になる理由

1. **事前IAM設定（セクション7.1 ステップ3）**: Owner権限者がサービスアカウント作成とプロジェクトレベルの権限を付与
   - `terraform-sa`: Editor、Service Account User、Secret Manager Admin
   - `streamlit-sa`: Pub/Sub Publisher、Run Invoker
   - `batch-worker-sa`: Pub/Sub Subscriber

2. **terraform apply後のIAM設定（セクション7.5）**: GCSバケットとSecret ManagerはTerraformで作成されるため、作成後に権限を付与
   - GCSバケット名とSecret IDが確定してから権限を追加
   - Owner権限者が`gcloud`コマンドで手動設定

**この方式のメリット**:

- `terraform-sa`に過剰な権限（`roles/iam.securityAdmin`）を付与する必要がない
- サービスアカウントキーファイルの共有が不要（impersonation使用）
- セキュリティリスクを最小化

### 6.9. ルートモジュール実装例

#### `providers.tf`

```hcl
provider "google" {
  project = var.project_id
  region  = var.region
}
```

#### `variables.tf`

```hcl
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "asia-northeast1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "streamlit_image" {
  description = "Streamlit container image"
  type        = string
}

variable "batch_worker_image" {
  description = "Batch worker container image"
  type        = string
}

variable "vpc_name" {
  description = "VPC network name"
  type        = string
}

variable "redis_instance_name" {
  description = "Redis instance name"
  type        = string
}

variable "gcs_bucket_name" {
  description = "GCS bucket name"
  type        = string
}

variable "pubsub_topic_name" {
  description = "Pub/Sub topic name"
  type        = string
}

variable "pubsub_sub_name" {
  description = "Pub/Sub subscription name"
  type        = string
}
```

#### `main.tf`

```hcl
# 手動作成されたサービスアカウントを参照
data "google_service_account" "streamlit" {
  account_id = "streamlit-sa"
}

data "google_service_account" "batch_worker" {
  account_id = "batch-worker-sa"
}

# VPCモジュール
module "vpc" {
  source = "./modules/vpc"

  vpc_name    = var.vpc_name
  region      = var.region
  environment = var.environment
}

# Redisモジュール
module "redis" {
  source = "./modules/redis"

  redis_instance_name    = var.redis_instance_name
  region                 = var.region
  vpc_id                 = module.vpc.network_id
  environment            = var.environment
  streamlit_sa_email     = data.google_service_account.streamlit.email
  batch_worker_sa_email  = data.google_service_account.batch_worker.email

  depends_on = [module.vpc]
}

# Pub/Subモジュール（Push型設定）
module "pubsub" {
  source = "./modules/pubsub"

  topic_name                   = var.pubsub_topic_name
  subscription_name            = var.pubsub_sub_name
  environment                  = var.environment
  batch_worker_url             = module.cloud_run_worker.service_url  # Push先のCloud Run URL
  pubsub_service_account_email = data.google_service_account.batch_worker.email  # batch-worker-saを使用

  depends_on = [module.cloud_run_worker]  # Cloud Run作成後にサブスクリプション作成
}

# GCSモジュール
module "storage" {
  source = "./modules/storage"

  bucket_name            = var.gcs_bucket_name
  region                 = var.region
  environment            = var.environment
  streamlit_sa_email     = data.google_service_account.streamlit.email
  batch_worker_sa_email  = data.google_service_account.batch_worker.email
}

# Cloud Runモジュール（Streamlit Frontend）
module "cloud_run" {
  source = "./modules/cloud-run"

  service_name          = "streamlit-app"
  region                = var.region
  container_image       = var.streamlit_image
  service_account_email = data.google_service_account.streamlit.email
  gcs_bucket_name       = module.storage.bucket_name
  pubsub_topic_name     = module.pubsub.topic_name
  redis_host_secret_id  = module.redis.redis_host_secret_id
  vpc_connector_id      = module.vpc.vpc_connector_id
  project_id            = var.project_id

  depends_on = [module.vpc, module.redis, module.pubsub, module.storage]
}

# Cloud Run Serviceモジュール（Batch Worker - Push型）
module "cloud_run_worker" {
  source = "./modules/cloud-run-worker"

  service_name          = "batch-worker-service"
  region                = var.region
  container_image       = var.batch_worker_image
  service_account_email = data.google_service_account.batch_worker.email
  gcs_bucket_name       = module.storage.bucket_name
  redis_host_secret_id  = module.redis.redis_host_secret_id
  vpc_connector_id      = module.vpc.vpc_connector_id
  project_id            = var.project_id

  depends_on = [module.vpc, module.redis, module.storage]
}
```

#### `outputs.tf`

```hcl
output "streamlit_url" {
  description = "Streamlit Cloud Run service URL"
  value       = module.cloud_run.service_url
}

output "batch_worker_url" {
  description = "Batch Worker Cloud Run service URL"
  value       = module.cloud_run_worker.service_url
}

output "gcs_bucket_name" {
  description = "GCS bucket name"
  value       = module.storage.bucket_name
}

output "redis_host" {
  description = "Redis instance host IP"
  value       = module.redis.redis_host
}

output "pubsub_topic" {
  description = "Pub/Sub topic full path"
  value       = module.pubsub.topic_id
}

output "redis_secret_id" {
  description = "Redis host Secret Manager ID"
  value       = module.redis.redis_host_secret_id
}

output "vpc_connector_id" {
  description = "VPC Access Connector ID"
  value       = module.vpc.vpc_connector_id
}
```

## 7. デプロイ手順

### 7.1. 事前準備（初回のみ）

#### ステップ1: GCPプロジェクト作成

```bash
# プロジェクトID設定
export PROJECT_ID="pdf-batch-processing-prod"
export REGION="asia-northeast1"

# プロジェクト作成
gcloud projects create $PROJECT_ID --name="PDF Batch Processing"

# プロジェクト設定
gcloud config set project $PROJECT_ID

# 課金アカウント有効化（手動で実施）
# https://console.cloud.google.com/billing
```

#### ステップ2: 必要なAPIを有効化

```bash
gcloud services enable compute.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  redis.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  vpcaccess.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

#### ステップ3: Terraform State用GCSバケット作成

**重要**: このバケットは`terraform init`前に必要なため、最初に作成します。

```bash
# バケット作成
gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://${PROJECT_ID}-tfstate

# バージョニング有効化（State破損時のロールバック用）
gsutil versioning set on gs://${PROJECT_ID}-tfstate

# 作成確認
gsutil ls -L gs://${PROJECT_ID}-tfstate | grep "Versioning"
# 期待される出力: Versioning enabled: True
```

#### ステップ4: サービスアカウントとIAMロール設定（Owner権限者が実施）

**重要**: この作業はプロジェクトOwner権限を持つ担当者が実施します。セキュリティ重視のため、以下の方針を採用します：

- **Terraform-SA**: リソース管理のみ（IAMロール付与権限なし）
- **アプリケーションSA**: 手動作成・手動でロール付与
- **キーファイル共有**: 不要（Editor権限者が自身の認証情報で実行）

以下のコマンドを**Owner権限者が順番に実行**してください。

##### 3-1. Terraform実行用サービスアカウント作成

```bash
# 1. terraform-sa作成
gcloud iam service-accounts create terraform-sa \
  --display-name="Terraform Service Account for Infrastructure Management"

# 2. リソース管理権限付与（IAMロール付与権限は含まれない）
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/editor"

# 3. サービスアカウント使用権限
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

# 4. Secret Manager管理権限
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.admin"

# 5. Editor権限者にimpersonation権限付与（キーファイル不要）
# EDITOR_EMAIL を実際のメールアドレスに置き換えてください
gcloud iam service-accounts add-iam-policy-binding \
  terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com \
  --member="user:EDITOR_EMAIL@example.com" \
  --role="roles/iam.serviceAccountTokenCreator"
```

##### 3-2. Streamlit Frontend用サービスアカウント作成

```bash
# 1. streamlit-sa作成
gcloud iam service-accounts create streamlit-sa \
  --display-name="Streamlit Frontend Service Account"

# 2. Pub/Sub Publisher権限（プロジェクトレベル）
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# 3. Cloud Run Invoker権限（自身のサービスを起動）
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

**注意**: Storage（GCS）とSecret Managerの権限は、バケット作成後に追加します（ステップ7.4後）。

##### 3-3. Batch Worker用サービスアカウント作成

```bash
# 1. batch-worker-sa作成
gcloud iam service-accounts create batch-worker-sa \
  --display-name="Batch Worker Service Account"
```

**注意**: Push型Pub/Subでは、`batch-worker-sa`にPub/Sub Subscriber権限は不要です。Storage（GCS）とSecret Managerの権限は、バケット作成後に追加します（セクション7.5参照）。Pub/SubサービスアカウントからのCloud Run呼び出し権限は、Terraformで自動設定されます（セクション6.7参照）。

##### 3-4. 作成確認

```bash
# サービスアカウント一覧確認
gcloud iam service-accounts list --filter="email:*-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# 期待される出力:
# terraform-sa@PROJECT_ID.iam.gserviceaccount.com
# streamlit-sa@PROJECT_ID.iam.gserviceaccount.com
# batch-worker-sa@PROJECT_ID.iam.gserviceaccount.com
```

**Owner権限者の作業はここまでです。** 以降はEditor権限者（Terraform実行者）が作業します。

**重要な設計変更**: 当初設計ではterraform apply後にOwner権限者が手動でIAM権限を追加する予定でしたが、セキュリティとメンテナンス性を考慮し、**全てのIAM設定をTerraformモジュール（`modules/redis`、`modules/storage`）に含める方式に変更しました。** これにより、terraform apply一回で全てのリソースとIAM権限が自動設定されます。

### 7.2. Dockerイメージビルドとプッシュ

#### Artifact Registry準備

```bash
# リポジトリ作成
gcloud artifacts repositories create docker-repo \
  --repository-format=docker \
  --location=$REGION \
  --description="Docker images for PDF batch processing"

# Docker認証設定
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

#### Streamlit Frontendビルド

**重要**: Cloud RunはAMD64アーキテクチャを使用するため、Mac（ARM64/M1/M2）でビルドする場合は`--platform linux/amd64`オプションが必須です。

```bash
cd apps/streamlit-app

# イメージビルド（AMD64アーキテクチャ指定）
docker buildx build --platform linux/amd64 -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest --load .

# プッシュ
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest
```

#### Batch Workerビルド

```bash
cd apps/batch-worker

# イメージビルド（AMD64アーキテクチャ指定）
docker buildx build --platform linux/amd64 -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest --load .

# プッシュ
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest
```

**注意**:

- `--platform linux/amd64`: Cloud Run用にAMD64アーキテクチャでビルド（Mac M1/M2でも動作）
- `--load`: ローカルDockerにイメージを読み込む（プッシュ前に必要）
- ARM64でビルドしたイメージをデプロイすると、Cloud Runで`exec format error`が発生します

### 7.3. Terraform変数設定 (`terraform.tfvars`)

```hcl
project_id     = "pdf-batch-processing-prod"
region         = "asia-northeast1"
environment    = "production"

# コンテナイメージ
streamlit_image     = "asia-northeast1-docker.pkg.dev/pdf-batch-processing-prod/docker-repo/streamlit-app:latest"
batch_worker_image  = "asia-northeast1-docker.pkg.dev/pdf-batch-processing-prod/docker-repo/batch-worker:latest"

# リソース名
vpc_name             = "pdf-processing-vpc"
redis_instance_name  = "pdf-status-redis"
gcs_bucket_name      = "pdf-batch-processing-prod-storage"
pubsub_topic_name    = "pdf-processing-topic"
pubsub_sub_name      = "pdf-processing-subscription"
```

#### 7.3.1. アプリケーション環境変数一覧

Cloud RunとCloud Run Jobsに設定される環境変数の完全なリスト:

##### Streamlit Frontend（Cloud Run）

| 環境変数名        | 説明              | 設定値の例                          | 設定元         |
| ----------------- | ----------------- | ----------------------------------- | -------------- |
| `STORAGE_TYPE`    | ストレージタイプ  | `GCP`                               | Terraform      |
| `GCS_BUCKET_NAME` | GCSバケット名     | `pdf-batch-processing-prod-storage` | Terraform      |
| `PUBSUB_TOPIC`    | Pub/Subトピック名 | `pdf-processing-topic`              | Terraform      |
| `GCP_PROJECT_ID`  | GCPプロジェクトID | `pdf-batch-processing-prod`         | Terraform      |
| `REDIS_HOST`      | RedisホストIP     | `10.0.1.3`                          | Secret Manager |
| `REDIS_PORT`      | Redisポート番号   | `6379`                              | Terraform      |

##### Batch Worker（Cloud Run Jobs）

| 環境変数名            | 説明                        | 設定値の例                          | 設定元         |
| --------------------- | --------------------------- | ----------------------------------- | -------------- |
| `STORAGE_TYPE`        | ストレージタイプ            | `GCP`                               | Terraform      |
| `GCS_BUCKET_NAME`     | GCSバケット名               | `pdf-batch-processing-prod-storage` | Terraform      |
| `PUBSUB_SUBSCRIPTION` | Pub/Subサブスクリプション名 | `pdf-processing-subscription`       | Terraform      |
| `GCP_PROJECT_ID`      | GCPプロジェクトID           | `pdf-batch-processing-prod`         | Terraform      |
| `REDIS_HOST`          | RedisホストIP               | `10.0.1.3`                          | Secret Manager |
| `REDIS_PORT`          | Redisポート番号             | `6379`                              | Terraform      |

**注意**: `REDIS_HOST`はSecret Manager経由で注入されます。他の環境変数はTerraformで直接設定されます。

### 7.4. Terraformデプロイ

```bash
cd terraform

# 初期化
terraform init

# 設定確認
terraform plan

# デプロイ実行
terraform apply

# 出力確認
terraform output
```

**予想される出力**:

```
streamlit_url = "https://streamlit-app-xxxxx-an.a.run.app"
gcs_bucket_name = "pdf-batch-processing-prod-storage"
redis_host = "10.0.1.3"
pubsub_topic = "projects/pdf-batch-processing-prod/topics/pdf-processing-topic"
redis_secret_id = "redis-host"
```

### 7.5. IAM権限の確認

**重要**: このプロジェクトでは、GCS・Secret ManagerのIAM権限はTerraformモジュール（`modules/storage`、`modules/redis`）に含まれているため、`terraform apply`完了時点で全ての権限が自動的に設定されます。**手動でのIAM設定は不要です。**

#### IAM設定の確認（オプション）

権限が正しく設定されているか確認する場合は、以下のコマンドを実行してください：

```bash
# Secret Managerの権限確認
gcloud secrets get-iam-policy redis-host --format=json | jq '.bindings[] | select(.role=="roles/secretmanager.secretAccessor")'

# GCSバケットの権限確認
export GCS_BUCKET_NAME=$(cd terraform && terraform output -raw gcs_bucket_name)
gcloud storage buckets get-iam-policy gs://${GCS_BUCKET_NAME} --format=json | jq '.bindings[] | select(.role | contains("storage"))'
```

**期待される結果**:

- `streamlit-sa`と`batch-worker-sa`が`secretmanager.secretAccessor`権限を持つ
- `streamlit-sa`が`storage.objectViewer`と`storage.objectCreator`権限を持つ
- `batch-worker-sa`が`storage.objectAdmin`権限を持つ

### 7.6. Push型Pub/Subの動作確認

**重要**: Push型では、手動でワーカーを起動する必要はありません。Pub/Subがメッセージを受信すると、自動的にBatch Worker（Cloud Run Service）がHTTP POSTで呼び出されます。

#### Pub/Sub設定確認

```bash
# サブスクリプション設定確認（Push設定が含まれているか確認）
gcloud pubsub subscriptions describe pdf-processing-subscription

# 期待される出力:
# pushConfig:
#   oidcToken:
#     serviceAccountEmail: batch-worker-sa@PROJECT_ID.iam.gserviceaccount.com
#   pushEndpoint: https://batch-worker-service-xxxxx-an.a.run.app
```

#### テストメッセージ送信

```bash
# テストメッセージを送信して、Batch Workerが呼び出されるか確認
gcloud pubsub topics publish pdf-processing-topic --message='{"job_id": "test-001", "file_path": "test.pdf"}'

# Batch Workerのログを確認（メッセージが処理されているか確認）
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=batch-worker-service" \
  --limit=10 \
  --format=json
```

**期待される動作**:

1. メッセージ送信後、数秒以内にBatch Workerが起動（コールドスタートの場合は10-20秒）
2. ログにメッセージ処理の記録が表示される
3. 処理完了後、200 OKを返してメッセージが削除される

### 7.7. デプロイ手順の完全な流れ（まとめ）

以下は、初めてデプロイする際の完全な手順です。手順漏れを防ぐため、上から順番に実行してください。

#### Phase 1: Owner権限者の事前準備（セクション7.1）

```bash
# 1. 環境変数設定
export PROJECT_ID="your-project-id"
export REGION="asia-northeast1"

# 2. プロジェクト設定
gcloud config set project $PROJECT_ID

# 3. API有効化
gcloud services enable compute.googleapis.com run.googleapis.com pubsub.googleapis.com redis.googleapis.com storage.googleapis.com secretmanager.googleapis.com vpcaccess.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

# 4. Terraform State用GCSバケット作成
gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://${PROJECT_ID}-tfstate
gsutil versioning set on gs://${PROJECT_ID}-tfstate

# 5. サービスアカウント作成（terraform-sa, streamlit-sa, batch-worker-sa）
# ステップ3-1〜3-3のコマンドを実行

# Owner権限者の作業完了
```

#### Phase 2: Editor権限者のDockerイメージビルド（セクション7.2）

```bash
# 1. Artifact Registry作成
gcloud artifacts repositories create docker-repo --repository-format=docker --location=$REGION
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# 2. Streamlitイメージビルド（AMD64必須）
cd apps/streamlit-app
docker buildx build --platform linux/amd64 -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest --load .
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest

# 3. Batch Workerイメージビルド（AMD64必須）
cd ../batch-worker
docker buildx build --platform linux/amd64 -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest --load .
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest
```

#### Phase 3: Terraform実行（セクション7.3〜7.4）

```bash
# 1. terraform.tfvars編集
cd ../../terraform
# terraform.tfvarsに環境変数を設定（project_id, region, container_imageなど）

# 2. Terraform初期化
terraform init

# 3. Terraform plan確認
terraform plan

# 4. Terraform apply実行
terraform apply -auto-approve

# 5. 出力確認
terraform output
```

#### Phase 4: 動作確認（セクション8）

```bash
# 1. Streamlit URLにアクセス
export STREAMLIT_URL=$(terraform output -raw streamlit_url)
open $STREAMLIT_URL

# 2. テストメッセージ送信
gcloud pubsub topics publish pdf-processing-topic --message='{"job_id": "test-001", "pdf_path": "test.pdf"}'

# 3. Batch Workerログ確認
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=batch-worker-service" --limit=10
```

**重要な注意事項:**

- Dockerイメージは必ず`--platform linux/amd64`でビルドしてください（ARM64はCloud Runで動作しません）
- VPC Connector名は24文字以内、min_instances=2が必須
- IAM権限は全てTerraformで自動設定されるため、terraform apply後の手動設定は不要です

## 8. 動作確認

### 8.1. Streamlitアクセス

```bash
# Cloud Run URLを取得
export STREAMLIT_URL=$(terraform output -raw streamlit_url)

# ブラウザで開く
open $STREAMLIT_URL
```

### 8.2. PDFアップロードとジョブ実行

1. Streamlit UIでPDFファイルをアップロード
2. 「解析開始」ボタンをクリック
3. 進捗バーでリアルタイム進捗を確認
4. 処理完了後、結果ファイルをダウンロード

### 8.3. ログ確認

#### Streamlitログ

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=streamlit-app" \
  --limit=50 \
  --format=json
```

#### Batch Workerログ

```bash
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=batch-worker-job" \
  --limit=50 \
  --format=json
```

### 8.4. Redis接続確認

```bash
# Redis IPを取得
REDIS_HOST=$(gcloud redis instances describe pdf-status-redis --region=$REGION --format="value(host)")

echo "Redis Host: $REDIS_HOST"

# 接続確認方法1: Cloud Runサービスのログから確認
# アプリケーションがRedisに接続した際のログを確認

# 接続確認方法2: 一時的なテスト用Cloud Run Jobsで確認
# Redisクライアントを含むコンテナイメージを使用

# Redisコマンド実行例（Cloud Run内から）
# import redis
# r = redis.Redis(host='REDIS_HOST', port=6379)
# r.keys('job:*')
# r.get('job:{job_id}')
```

**注意**: Cloud Memorystore (Redis) はVPC内部からのみアクセス可能です。Cloud Shellから直接接続することはできません。接続確認は、VPC ConnectorでRedisに接続可能なCloud RunまたはCloud Run Jobsから行う必要があります。

### 8.5. GCSファイル確認

```bash
# アップロードされたファイル一覧
gsutil ls gs://${PROJECT_ID}-storage/uploads/

# 結果ファイル一覧
gsutil ls gs://${PROJECT_ID}-storage/results/

# Lifecycle確認（24時間経過後のファイルが削除されることを確認）
gsutil lifecycle get gs://${PROJECT_ID}-storage
```

## 9. トラブルシューティング

### 9.0. よくある問題と解決策（デプロイ時）

#### 問題1: VPC Connector名が長すぎる

**症状**: `Error 400: Connector ID must follow the pattern ^[a-z][-a-z0-9]{0,23}[a-z0-9]$`

**原因**: VPC Connector名は24文字以内（英小文字・数字・ハイフンのみ）

**解決策**: `modules/vpc/main.tf`で名前を短縮

```hcl
name = "pdf-vpc-connector"  # OK (17文字)
name = "${var.vpc_name}-connector"  # NG (28文字の場合がある)
```

#### 問題2: VPC Connector min_instances=0 エラー

**症状**: `Error 400: The minimum amount of instances underlying the connector must be at least 2`

**原因**: GCPの制約でmin_instances=0は設定不可

**解決策**: `modules/vpc/main.tf`で最小値を2に設定

```hcl
min_instances = 2  # GCP最小値
```

#### 問題3: Docker exec format error

**症状**: Cloud Runログに`exec format error`または`failed to load /bin/sh: exec format error`

**原因**: ARM64（Mac M1/M2）でビルドしたイメージをAMD64のCloud Runにデプロイ

**解決策**: AMD64アーキテクチャでリビルド

```bash
docker buildx build --platform linux/amd64 -t IMAGE_NAME --load .
docker push IMAGE_NAME
```

#### 問題4: Pub/Sub subscription作成エラー（iam.serviceAccounts.actAs）

**症状**: `Error 403: Principal initiating the request does not have iam.serviceAccounts.actAs permission`

**原因**: Pub/SubサービスアカウントにOIDC認証を設定しようとしたが、権限不足

**解決策**: `batch-worker-sa`をOIDC認証に使用（`modules/pubsub/main.tf`で設定）

```hcl
oidc_token {
  service_account_email = var.pubsub_service_account_email  # batch-worker-saのemailを渡す
}
```

#### 問題5: Terraform State lock

**症状**: `Error acquiring the state lock`

**原因**: 前回のterraform操作が異常終了してロックが残っている

**解決策**: 強制的にロックを解除

```bash
terraform force-unlock -force LOCK_ID
```

#### 問題6: Cloud Run Service削除エラー（deletion_protection）

**症状**: `Error: cannot destroy service without setting deletion_protection=false`

**原因**: Cloud Run Serviceはデフォルトで削除保護が有効

**解決策**: 手動で削除してからterraform apply

```bash
gcloud run services delete SERVICE_NAME --region=REGION --quiet
terraform apply
```

## 9. トラブルシューティング（運用時）

### 9.1. Cloud Runがタイムアウトする

**症状**: Streamlitアプリが503エラーを返す

**原因**: タイムアウト設定が短すぎる、またはRedis接続に失敗

**解決策**:

```bash
# タイムアウトを延長
gcloud run services update streamlit-app \
  --timeout=300 \
  --region=$REGION

# VPCコネクタ接続確認
gcloud compute networks vpc-access connectors describe pdf-processing-vpc-connector \
  --region=$REGION
```

### 9.2. Redis接続エラー

**症状**: `ConnectionError: Error 111 connecting to 10.0.1.3:6379. Connection refused.`

**原因**: VPCコネクタ未設定、またはファイアウォールルール不足

**解決策**:

```bash
# ファイアウォールルール確認
gcloud compute firewall-rules list --filter="name~redis"

# VPCコネクタのステータス確認
gcloud compute networks vpc-access connectors list --region=$REGION
```

### 9.3. Pub/Subメッセージが処理されない

**症状**: ジョブがキューに溜まり続ける

**原因**: Cloud Run Jobsが起動していない、またはサブスクリプションACK期限切れ

**解決策**:

```bash
# サブスクリプションの未処理メッセージ数確認
gcloud pubsub subscriptions describe pdf-processing-subscription

# Cloud Run Jobsを手動実行
gcloud run jobs execute batch-worker-job --region=$REGION

# ACK期限を延長（Terraformで再適用）
# ack_deadline_seconds = 600 → 1200
```

### 9.4. GCSライフサイクルが動作しない

**症状**: 24時間経過してもファイルが削除されない

**原因**: Lifecycle Ruleの設定ミス、またはタイムゾーン誤認識

**重要**: GCS Lifecycleの`age = 1`は**UTC 00:00基準**で計算されます。

- 日本時間（JST）との9時間の時差があるため、削除タイミングが予想と異なる場合があります
- 例: JST 2026-02-13 21:00にアップロードしたファイルは、UTC基準では2026-02-13 12:00となり、翌日UTC 00:00（JST 09:00）に削除されます

**解決策**:

```bash
# Lifecycle設定確認
gsutil lifecycle get gs://${PROJECT_ID}-storage

# ファイルの作成日時確認（UTC）
gsutil ls -l gs://${PROJECT_ID}-storage/uploads/

# 手動削除で動作確認
gsutil rm gs://${PROJECT_ID}-storage/uploads/test-file.pdf
```

## 10. 運用・保守

### 10.1. デプロイの更新

アプリケーションコード変更時の更新手順:

```bash
# 1. Dockerイメージ再ビルド・プッシュ
cd apps/streamlit-app
docker build -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest .
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest

# 2. Cloud Runを再デプロイ（新しいイメージを適用）
gcloud run services update streamlit-app \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest \
  --region=$REGION

# 3. Terraform適用（インフラ変更がある場合）
cd terraform
terraform apply
```

### 10.2. スケーリング設定

```bash
# Cloud Runの最大インスタンス数設定
gcloud run services update streamlit-app \
  --max-instances=10 \
  --region=$REGION

# Cloud Run Jobsの並列タスク数変更（Terraformで変更）
# task_count = 3 → 5
```

### 10.3. モニタリング

```bash
# Cloud Monitoringダッシュボード作成
# https://console.cloud.google.com/monitoring

# アラート設定（例: Cloud Runエラー率 > 5%）
gcloud alpha monitoring policies create \
  --notification-channels=EMAIL_CHANNEL_ID \
  --display-name="Cloud Run Error Rate Alert" \
  --condition-display-name="Error Rate > 5%" \
  --condition-threshold-value=0.05
```

### 10.4. コスト最適化

| リソース                  | 月額推定コスト | 最適化施策                                    |
| ------------------------- | -------------- | --------------------------------------------- |
| Cloud Memorystore (Redis) | ¥5,500〜       | Firestore/Cloud Run内メモリへの移行検討       |
| Cloud Run                 | ¥500〜         | 最小インスタンス数0、アイドルタイムアウト設定 |
| Cloud Storage             | ¥100〜         | Lifecycle Rule 24時間削除で自動削減           |
| Cloud Pub/Sub             | ¥100〜         | メッセージ保持期間1日で設定済み               |
| VPC Connector             | ¥1,000〜¥2,000 | min_instances=2（GCP制約）常時稼働            |

**合計**: 約¥7,200〜/月（軽負荷時）

**注意**: VPC Connectorは最小インスタンス数2が必須（GCPの制約）のため、月額約¥1,000〜¥2,000の固定費が発生します。

**注意**: Cloud Memorystore (Redis Basic 1GB) は月額約¥5,500〜¥6,000です。コスト削減が必要な場合は、Redisをやめて代替手段（Firestore、Cloud Run内メモリ）を検討してください。

## 11. セキュリティ考慮事項

### 11.1. 認証・認可

- **現状**: Cloud Runは認証なし（`allUsers`に公開）
- **本番推奨**: Identity-Aware Proxy (IAP) でGoogle Workspace認証を追加

```bash
# IAP有効化（別途設定が必要）
gcloud iap web enable --resource-type=app-engine
```

### 11.2. データ保護

- **暗号化**: GCSは自動的にサーバーサイド暗号化（AES-256）
- **TTL**: 24時間でデータ自動削除（GDPR/個人情報保護法対応）
- **Redis TLS**: 本番環境では`transit_encryption_mode = "SERVER_AUTH"`を推奨

### 11.3. ネットワーク分離

- **VPC**: Cloud Memorystore専用VPCで分離
- **Private IP**: Redisは外部アクセス不可（VPC内のみ）
- **Egress制御**: Cloud Run/JobsはVPCコネクタ経由でのみRedis接続

## 12. 引き継ぎチェックリスト

### デプロイ完了確認

- [ ] GCPプロジェクトが作成され、課金が有効化されている
- [ ] 必要なAPIが全て有効化されている
- [ ] Terraform State用GCSバケットが作成されている
- [ ] Dockerイメージが Artifact Registry にプッシュされている
- [ ] `terraform apply` が成功し、全リソースが作成されている
- [ ] Streamlit URLにアクセスでき、UIが表示される
- [ ] PDFアップロード → 解析 → 結果ダウンロードのフローが動作する
- [ ] Redisに接続でき、ステータスが更新される
- [ ] Cloud Logsでエラーが発生していない
- [ ] GCS Lifecycleが設定され、24時間後にファイルが削除される

### ドキュメント確認

- [ ] `terraform.tfvars` に本番環境のプロジェクトIDが設定されている
- [ ] サービスアカウントが手動で作成され、適切な権限が付与されている
- [ ] 本設計書が最新の状態にアップデートされている
- [ ] トラブルシューティング手順が確認されている

## 13. 今後の改善案

- **CI/CDパイプライン**: GitHub ActionsまたはCloud Buildで自動デプロイ
- **IAP導入**: Google Workspace認証でセキュリティ強化
- **マルチリージョン**: Cloud Storageをマルチリージョンバケットに変更
- **Cloud Armor**: DDoS対策とWAFの導入
- **Cost Optimization**: Cloud Memorystore → Firestore移行でコスト50%削減
- **ヘルスチェックエンドポイント**: Cloud Runに`/health`エンドポイントを実装し、起動確認とロードバランサーのヘルスチェックを容易にする
- **Pub/Subデッドレターポリシー**: 処理失敗時のメッセージを別トピックに送信し、再処理を容易にする

## 14. 付録: Owner権限者向け実施手順書（完全版）

このセクションは、プロジェクトOwner権限を持つ担当者が実施する全手順をまとめたものです。
実施者はこのセクションの手順を上から順番に実行してください。

### 前提条件

- GCPプロジェクトOwner権限を持つアカウント
- gcloud CLIがインストール済み
- プロジェクトIDと実施者のメールアドレスを準備

### 手順1: 環境変数の設定

```bash
# プロジェクトID（実際の値に置き換える）
export PROJECT_ID="pdf-batch-processing-prod"
export REGION="asia-northeast1"

# Editor権限者のメールアドレス（Terraform実行者、実際の値に置き換える）
export EDITOR_EMAIL="editor@example.com"

# プロジェクト設定
gcloud config set project $PROJECT_ID
```

### 手順2: GCP APIの有効化

```bash
gcloud services enable compute.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  redis.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  vpcaccess.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

# 有効化確認（全てSTATEがENABLEDになることを確認）
gcloud services list --enabled | grep -E "(compute|run|pubsub|redis|storage|secretmanager|vpcaccess|artifactregistry|cloudbuild)"
```

### 手順3: Terraform State用GCSバケット作成

```bash
# バケット作成
gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://${PROJECT_ID}-tfstate

# バージョニング有効化
gsutil versioning set on gs://${PROJECT_ID}-tfstate

# 作成確認
gsutil ls -L gs://${PROJECT_ID}-tfstate | grep "Versioning"
# 出力: Versioning enabled: True
```

### 手順4: terraform-sa の作成と権限付与

```bash
# 1. サービスアカウント作成
gcloud iam service-accounts create terraform-sa \
  --display-name="Terraform Service Account for Infrastructure Management"

# 2. Editor権限付与
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/editor"

# 3. サービスアカウント使用権限
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

# 4. Secret Manager管理権限
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.admin"

# 5. Editor権限者にimpersonation権限付与
gcloud iam service-accounts add-iam-policy-binding \
  terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com \
  --member="user:${EDITOR_EMAIL}" \
  --role="roles/iam.serviceAccountTokenCreator"

# 作成確認
gcloud iam service-accounts describe terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com
```

### 手順5: streamlit-sa の作成と権限付与

```bash
# 1. サービスアカウント作成
gcloud iam service-accounts create streamlit-sa \
  --display-name="Streamlit Frontend Service Account"

# 2. Pub/Sub Publisher権限
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# 3. Cloud Run Invoker権限
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# 作成確認
gcloud iam service-accounts describe streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com
```

### 手順6: batch-worker-sa の作成

```bash
# 1. サービスアカウント作成
gcloud iam service-accounts create batch-worker-sa \
  --display-name="Batch Worker Service Account"

# 作成確認
gcloud iam service-accounts describe batch-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com
```

**注意**: Push型Pub/Subでは、batch-worker-saにPub/Sub Subscriber権限は不要です。Pub/SubサービスアカウントからのCloud Run呼び出し権限は、Terraformで自動設定されます。

### 手順7: サービスアカウント一覧確認

```bash
# 全サービスアカウント確認
gcloud iam service-accounts list --filter="email:*-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# 期待される出力:
# DISPLAY NAME                                      EMAIL                                         DISABLED
# Terraform Service Account for Infrastructure...  terraform-sa@PROJECT_ID.iam.gserviceaccount.com  False
# Streamlit Frontend Service Account                streamlit-sa@PROJECT_ID.iam.gserviceaccount.com  False
# Batch Worker Service Account                      batch-worker-sa@PROJECT_ID.iam.gserviceaccount.com  False
```

### 手順8: Editor権限者への引き継ぎ事項

以下の情報をEditor権限者（Terraform実行者）に伝えてください：

```
プロジェクトID: ${PROJECT_ID}
リージョン: ${REGION}

作成済みサービスアカウント:
- terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com
- streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com
- batch-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com

Terraform State バケット: gs://${PROJECT_ID}-tfstate

次の作業:
1. Editor権限者がDockerイメージをビルド・プッシュ（AMD64アーキテクチャ指定）
2. Editor権限者がterraform applyを実行（impersonation使用）

注意事項:
- IAM権限は全てTerraformで自動設定されるため、terraform apply後の手動IAM設定は不要です
- Dockerイメージは必ず --platform linux/amd64 でビルドしてください
```

### 完了確認チェックリスト

全ての手順完了後、以下を確認してください：

- [ ] 手順1-7を順番に実行し、エラーなく完了した
- [ ] サービスアカウントが3つ作成されている（terraform-sa, streamlit-sa, batch-worker-sa）
- [ ] Terraform State用GCSバケットが作成されている
- [ ] Editor権限者に引き継ぎ事項を伝達した
- [ ] Editor権限者からterraform apply完了の連絡を受けた
- [ ] （手順9は不要 - IAM権限はTerraformで自動設定）

### トラブルシューティング

#### エラー: "Permission denied"

```bash
# 自分のアカウントがOwner権限を持っているか確認
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:user:YOUR_EMAIL@example.com"

# roles/owner が表示されることを確認
```

#### エラー: "Service account already exists"

```bash
# 既存のサービスアカウントを削除（慎重に実施）
gcloud iam service-accounts delete terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com
```

#### エラー: "API not enabled"

```bash
# 必要なAPIを再度有効化
gcloud services enable SERVICE_NAME.googleapis.com
```

### サポート連絡先

この手順書について不明点がある場合は、以下に連絡してください：

- **Editor権限者（Terraform実行者）**: ${EDITOR_EMAIL}
- **プロジェクト管理者**: （管理者の連絡先を記載）

---

## 15. 更新履歴

### 2026-02-13: 実デプロイ結果を反映した大幅更新

**背景**: 実際のGCPデプロイ作業を通じて得られた知見を反映し、再現性を確保するため全面的に更新。

**主な変更点**:

1. **Terraform Version要件変更**
   - 変更前: `>= 1.10.0`
   - 変更後: `>= 1.9.0`
   - 理由: 互換性確保、ローカル環境で1.9.8が主流

2. **VPC Connector設定修正**
   - 名前制限: 24文字以内（`pdf-vpc-connector`を推奨）
   - min_instances: 0 → 2（GCPの制約で最小2が必須）
   - 理由: デプロイ時にエラー発生、GCPドキュメント確認

3. **Dockerイメージアーキテクチャ明記**
   - 追加: `--platform linux/amd64`オプション必須
   - 理由: ARM64（Mac M1/M2）でビルドするとCloud Runで`exec format error`発生

4. **Pub/Sub OIDC認証方式変更**
   - 変更前: Pub/Subサービスアカウント（`service-${project_number}@gcp-sa-pubsub.iam.gserviceaccount.com`）
   - 変更後: batch-worker-sa
   - 理由: `iam.serviceAccounts.actAs`権限エラー回避

5. **IAM権限設定の自動化**
   - 変更前: terraform apply後にOwner権限者が手動でGCS・Secret ManagerのIAM権限を追加
   - 変更後: 全てのIAM権限をTerraformモジュール（`modules/redis`、`modules/storage`）に含める
   - 理由: 手動作業の排除、Infrastructure as Codeの完全実装

6. **variables.tf修正**
   - 削除: `project_number`変数（Pub/Subサービスアカウント方式廃止により不要）
   - 追加: `modules/redis`と`modules/storage`に`streamlit_sa_email`、`batch_worker_sa_email`変数

7. **トラブルシューティング追加**
   - デプロイ時に遭遇した6つの問題と解決策を新規追加
   - VPC Connector名エラー、min_instances制約、ARM64/AMD64問題、State lock、deletion_protectionなど

8. **デプロイ手順の完全フロー追加**
   - セクション7.7に4フェーズの詳細手順を追加
   - 手順漏れ防止のため、コマンドレベルで網羅

**削除された内容**:

- セクション7.5「残りのIAM設定」（自動化により不要）
- 付録セクション「手順9: Terraform Apply後の追加IAM設定」（自動化により不要）
- `project_number`変数とその取得方法の説明

**影響**:

- この更新により、初めてデプロイする担当者が手順通りに実行すれば、確実に成功するようになった
- terraform apply一回で全リソースとIAM権限が完全自動構築される
- 手動作業が大幅に削減され、ヒューマンエラーのリスクが低減

**検証済み**: 実際のGCP環境（PROJECT_ID: weekly-dev-20251013）で全手順を実行し、正常動作を確認済み
