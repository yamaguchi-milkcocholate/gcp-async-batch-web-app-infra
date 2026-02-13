# GCPデプロイ クイックスタートガイド

**対象**: 副業先の社員（Owner権限）とEditor権限者が協力して初めてデプロイする場合

**最終更新**: 2026-02-13（実環境で検証済み）

---

## 📋 目次

1. [前提条件](#前提条件)
2. [役割分担](#役割分担)
3. [Phase 1: Owner権限者の作業](#phase-1-owner権限者の作業)
4. [Phase 2: Editor権限者の作業（Dockerビルド）](#phase-2-editor権限者の作業dockerビルド)
5. [Phase 3: Editor権限者の作業（Terraformデプロイ）](#phase-3-editor権限者の作業terraformデプロイ)
6. [Phase 4: 動作確認](#phase-4-動作確認)
7. [よくある問題と対処法](#よくある問題と対処法)

---

## 前提条件

### 環境

- **OS**: macOS / Linux（Windowsの場合はWSL2推奨）
- **必要なツール**:
  - `gcloud` CLI（最新版）
  - Docker Desktop（Mac M1/M2の場合はBuildxが必須）
  - Terraform 1.9.0以上
  - `jq`（JSON処理用）

### GCPアカウント

- **Owner権限者**: GCPプロジェクトのOwner権限を持つアカウント
- **Editor権限者**: Editor権限（terraform-saにimpersonation可能）

### 確認事項

```bash
# gcloud CLIバージョン確認
gcloud version

# Dockerバージョン確認
docker --version
docker buildx version  # Mac M1/M2の場合

# Terraformバージョン確認
terraform version  # 1.9.0以上であること

# jq確認
jq --version
```

---

## 役割分担

| 作業フェーズ | 担当者           | 作業内容                                               | 所要時間 |
| ------------ | ---------------- | ------------------------------------------------------ | -------- |
| Phase 1      | **Owner権限者**  | GCPプロジェクト準備、サービスアカウント作成、API有効化 | 30分     |
| Phase 2      | **Editor権限者** | Dockerイメージビルド・プッシュ                         | 20分     |
| Phase 3      | **Editor権限者** | Terraform実行、インフラ構築                            | 20分     |
| Phase 4      | **両者**         | 動作確認                                               | 10分     |

**合計所要時間**: 約80分

---

## Phase 1: Owner権限者の作業

### ステップ1-1: 環境変数設定

```bash
# プロジェクトID（実際の値に置き換える）
export PROJECT_ID="your-project-id"
export REGION="asia-northeast1"

# Editor権限者のメールアドレス（実際の値に置き換える）
export EDITOR_EMAIL="editor@example.com"

# プロジェクト設定
gcloud config set project $PROJECT_ID
```

### ステップ1-2: GCP API有効化

```bash
gcloud services enable \
  compute.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  redis.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  vpcaccess.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

# 有効化確認（全てENABLEDと表示されること）
gcloud services list --enabled | grep -E "(compute|run|pubsub|redis|storage|secretmanager|vpcaccess|artifactregistry|cloudbuild)"
```

**確認ポイント**: 9個のAPIが全てENABLEDと表示されること

### ステップ1-3: Terraform State用GCSバケット作成

```bash
# バケット作成
gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://${PROJECT_ID}-tfstate

# バージョニング有効化（State破損時のロールバック用）
gsutil versioning set on gs://${PROJECT_ID}-tfstate

# 作成確認
gsutil ls -L gs://${PROJECT_ID}-tfstate | grep "Versioning"
# 期待される出力: Versioning enabled: True
```

**確認ポイント**: `Versioning enabled: True`と表示されること

### ステップ1-4: サービスアカウント作成（terraform-sa）

```bash
# 1. terraform-sa作成
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
```

**確認ポイント**: 5つのコマンドが全てエラーなく完了すること

### ステップ1-5: サービスアカウント作成（streamlit-sa）

```bash
# 1. streamlit-sa作成
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
```

**確認ポイント**: 3つのコマンドが全てエラーなく完了すること

### ステップ1-6: サービスアカウント作成（batch-worker-sa）

```bash
# batch-worker-sa作成
gcloud iam service-accounts create batch-worker-sa \
  --display-name="Batch Worker Service Account"
```

**注意**: batch-worker-saのGCS・Secret Manager権限はTerraformで自動設定されます。

### ステップ1-7: サービスアカウント確認

```bash
# 全サービスアカウント確認
gcloud iam service-accounts list --filter="email:*-sa@${PROJECT_ID}.iam.gserviceaccount.com"
```

**期待される出力**:

```
DISPLAY NAME                                      EMAIL
Terraform Service Account for Infrastructure...  terraform-sa@PROJECT_ID.iam.gserviceaccount.com
Streamlit Frontend Service Account                streamlit-sa@PROJECT_ID.iam.gserviceaccount.com
Batch Worker Service Account                      batch-worker-sa@PROJECT_ID.iam.gserviceaccount.com
```

**確認ポイント**: 3つのサービスアカウントが表示されること

### ステップ1-8: Editor権限者への連絡

以下の情報をEditor権限者に伝えてください：

```
件名: GCPデプロイ準備完了

プロジェクトID: ${PROJECT_ID}
リージョン: ${REGION}
Terraform State バケット: gs://${PROJECT_ID}-tfstate

作成済みサービスアカウント:
- terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com
- streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com
- batch-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com

次のステップ:
1. Dockerイメージをビルド・プッシュしてください（Phase 2）
2. Terraformでインフラを構築してください（Phase 3）

重要な注意事項:
- Dockerイメージは必ず --platform linux/amd64 でビルドしてください
- Mac M1/M2の場合、docker buildx を使用してください
```

**Owner権限者の作業完了チェックリスト**:

- [ ] 9個のGCP APIが有効化されている
- [ ] Terraform State用GCSバケットが作成され、バージョニングが有効
- [ ] 3つのサービスアカウントが作成されている
- [ ] Editor権限者にimpersonation権限が付与されている
- [ ] Editor権限者に必要な情報を連絡した

---

## Phase 2: Editor権限者の作業（Dockerビルド）

### ステップ2-1: リポジトリクローンと環境変数設定

```bash
# リポジトリをクローン（既にある場合はスキップ）
cd ~/workspace
git clone <リポジトリURL>
cd gcp-async-batch-web-app-infra

# 環境変数設定（Owner権限者から受け取った情報）
export PROJECT_ID="your-project-id"  # 実際の値に置き換える
export REGION="asia-northeast1"

# プロジェクト設定
gcloud config set project $PROJECT_ID
```

### ステップ2-2: Artifact Registry作成

```bash
# リポジトリ作成
gcloud artifacts repositories create docker-repo \
  --repository-format=docker \
  --location=$REGION \
  --description="Docker images for PDF batch processing"

# Docker認証設定
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

**確認ポイント**: `docker-repo`が作成されたこと

### ステップ2-3: Streamlitイメージビルド（AMD64必須）

```bash
cd apps/streamlit-app

# イメージビルド（AMD64アーキテクチャ指定）
docker buildx build --platform linux/amd64 \
  -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest \
  --load .

# プッシュ
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest
```

**重要**: `--platform linux/amd64`を必ず指定してください（ARM64でビルドするとCloud Runでエラーになります）

**確認ポイント**: プッシュが成功し、`latest: digest: sha256:...`と表示されること

### ステップ2-4: Batch Workerイメージビルド（AMD64必須）

```bash
cd ../batch-worker

# イメージビルド（AMD64アーキテクチャ指定）
docker buildx build --platform linux/amd64 \
  -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest \
  --load .

# プッシュ
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest
```

**確認ポイント**: プッシュが成功し、`latest: digest: sha256:...`と表示されること

### ステップ2-5: イメージ確認

```bash
# Artifact Registryのイメージ一覧確認
gcloud artifacts docker images list ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo
```

**期待される出力**:

```
IMAGE                                                                 DIGEST       CREATE_TIME
.../docker-repo/streamlit-app:latest                                  sha256:...   2026-02-13T...
.../docker-repo/batch-worker:latest                                   sha256:...   2026-02-13T...
```

**確認ポイント**: 2つのイメージが表示されること

**Dockerビルド完了チェックリスト**:

- [ ] Artifact Registryが作成されている
- [ ] Streamlitイメージがプッシュされている
- [ ] Batch Workerイメージがプッシュされている
- [ ] 両方のイメージがAMD64アーキテクチャでビルドされている

---

## Phase 3: Editor権限者の作業（Terraformデプロイ）

### ステップ3-1: terraform.tfvars編集

```bash
cd ../../terraform

# terraform.tfvarsを作成・編集
cat > terraform.tfvars <<EOF
project_id     = "${PROJECT_ID}"
region         = "${REGION}"
environment    = "production"

# コンテナイメージ
streamlit_image     = "${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest"
batch_worker_image  = "${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest"

# リソース名
vpc_name             = "pdf-processing-vpc"
redis_instance_name  = "pdf-status-redis"
gcs_bucket_name      = "${PROJECT_ID}-pdf-storage"
pubsub_topic_name    = "pdf-processing-topic"
pubsub_sub_name      = "pdf-processing-subscription"
EOF

# 設定確認
cat terraform.tfvars
```

**確認ポイント**: PROJECT_IDとREGIONが正しく設定されていること

### ステップ3-2: Terraform初期化

```bash
# 初期化
terraform init

# 期待される出力: "Terraform has been successfully initialized!"
```

**確認ポイント**: エラーなく初期化が完了すること

### ステップ3-3: Terraform plan確認

```bash
# 設定確認
terraform plan

# リソース数確認（最後の行を確認）
# 期待される出力: Plan: XX to add, 0 to change, 0 to destroy.
```

**確認ポイント**:

- エラーが発生しないこと
- 追加されるリソース数が表示されること（20個前後）

### ステップ3-4: Terraform apply実行

```bash
# デプロイ実行
terraform apply -auto-approve

# 処理時間: 約10-15分（Redis作成に時間がかかります）
```

**主な処理の流れ**:

1. VPC作成（約30秒）
2. VPC Connector作成（約2-3分）
3. Redis作成（約6-7分）
4. Secret Manager作成（約10秒）
5. Cloud Run Services作成（約30秒）
6. Pub/Sub作成（約10秒）
7. IAM権限設定（自動）

**確認ポイント**: `Apply complete!`と表示されること

### ステップ3-5: 出力確認

```bash
# Terraform出力確認
terraform output

# 期待される出力例:
# batch_worker_url = "https://batch-worker-service-xxxxx-an.a.run.app"
# gcs_bucket_name = "your-project-id-pdf-storage"
# pubsub_topic = "projects/your-project-id/topics/pdf-processing-topic"
# redis_host = "10.228.148.67"
# redis_secret_id = "redis-host"
# streamlit_url = "https://streamlit-app-xxxxx-an.a.run.app"
# vpc_connector_id = "projects/your-project-id/locations/asia-northeast1/connectors/pdf-vpc-connector"
```

**確認ポイント**: 全ての出力値が表示されること

**Terraformデプロイ完了チェックリスト**:

- [ ] terraform initが成功している
- [ ] terraform planでエラーが発生していない
- [ ] terraform applyが成功している
- [ ] 全ての出力値が表示されている
- [ ] streamlit_urlとbatch_worker_urlが取得できている

---

## Phase 4: 動作確認

### ステップ4-1: Streamlitアクセス確認

```bash
# Streamlit URLを取得
export STREAMLIT_URL=$(terraform output -raw streamlit_url)

# ブラウザで開く
open $STREAMLIT_URL
# Linuxの場合: xdg-open $STREAMLIT_URL
```

**確認ポイント**: StreamlitのUIが表示されること

### ステップ4-2: テストメッセージ送信

```bash
# Pub/Subにテストメッセージを送信
gcloud pubsub topics publish pdf-processing-topic \
  --project=$PROJECT_ID \
  --message='{"job_id": "test-001", "pdf_path": "test.pdf"}'

# 期待される出力:
# messageIds:
# - 'XXXXXXXXX'
```

**確認ポイント**: メッセージIDが表示されること

### ステップ4-3: Batch Workerログ確認

```bash
# 約10秒待ってからログ確認
sleep 10

# Batch Workerのログ確認
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=batch-worker-service" \
  --limit=20 \
  --project=$PROJECT_ID \
  --format=json | jq -r '.[] | "\(.timestamp) [\(.severity)] \(.textPayload // .jsonPayload.message // "")"'
```

**期待される出力例**:

```
2026-02-13T11:26:19.863Z [INFO] Job test-001 completed. Result: results/test-001/result.json
2026-02-13T11:26:19.863Z [INFO] [test-001] Processing completed in 20.18s
2026-02-13T11:26:19.862Z [DEBUG] [test-001] Status updated: completed (100%)
2026-02-13T11:26:19.860Z [INFO] File uploaded to GCS: gs://...
```

**確認ポイント**: ジョブ処理のログが表示されること

### ステップ4-4: GCS結果ファイル確認

```bash
# 結果ファイル確認
export GCS_BUCKET_NAME=$(terraform output -raw gcs_bucket_name)
gcloud storage ls gs://${GCS_BUCKET_NAME}/results/

# 結果ファイルの内容確認
gcloud storage cat gs://${GCS_BUCKET_NAME}/results/test-001/result.json
```

**期待される出力例**:

```json
{
  "job_id": "test-001",
  "pages": 5,
  "processed_at": "2026-02-13T11:26:19.700041+00:00",
  "processing_time_seconds": 20.18
}
```

**確認ポイント**: 結果ファイルが作成され、JSON形式で内容が表示されること

### ステップ4-5: IAM権限確認（オプション）

```bash
# Secret Managerの権限確認
gcloud secrets get-iam-policy redis-host \
  --format=json | jq '.bindings[] | select(.role=="roles/secretmanager.secretAccessor")'

# GCSバケットの権限確認
gcloud storage buckets get-iam-policy gs://${GCS_BUCKET_NAME} \
  --format=json | jq '.bindings[] | select(.role | contains("storage"))'
```

**確認ポイント**:

- `streamlit-sa`と`batch-worker-sa`がsecretmanager.secretAccessor権限を持つ
- `streamlit-sa`がstorage.objectViewer/Creator権限を持つ
- `batch-worker-sa`がstorage.objectAdmin権限を持つ

**動作確認完了チェックリスト**:

- [ ] Streamlit UIが表示される
- [ ] テストメッセージが送信できる
- [ ] Batch Workerがメッセージを処理している（ログ確認）
- [ ] GCSに結果ファイルが保存されている
- [ ] IAM権限が正しく設定されている

---

## よくある問題と対処法

### 問題1: Dockerイメージビルド時に`exec format error`

**症状**: Cloud Runのログに`exec format error`と表示される

**原因**: ARM64（Mac M1/M2）でビルドしたイメージをデプロイした

**解決策**: AMD64でリビルド

```bash
docker buildx build --platform linux/amd64 -t IMAGE_NAME --load .
docker push IMAGE_NAME

# Terraformで再デプロイ
cd terraform
terraform apply -auto-approve
```

### 問題2: Terraform apply時にVPC Connector名エラー

**症状**: `Error 400: Connector ID must follow the pattern ^[a-z][-a-z0-9]{0,23}[a-z0-9]$`

**原因**: VPC Connector名が24文字を超えている

**解決策**: `terraform/modules/vpc/main.tf`を確認

```hcl
# 正しい設定
resource "google_vpc_access_connector" "connector" {
  name = "pdf-vpc-connector"  # 17文字（OK）
  ...
}
```

### 問題3: Terraform apply時にmin_instancesエラー

**症状**: `Error 400: The minimum amount of instances underlying the connector must be at least 2`

**原因**: VPC ConnectorのGCP制約

**解決策**: `terraform/modules/vpc/main.tf`で確認

```hcl
resource "google_vpc_access_connector" "connector" {
  ...
  min_instances = 2  # 0は設定不可
  max_instances = 3
}
```

### 問題4: Terraform State lock

**症状**: `Error acquiring the state lock`

**原因**: 前回のterraform操作が異常終了

**解決策**: ロックを強制解除

```bash
# ロックIDはエラーメッセージに表示されます
terraform force-unlock -force LOCK_ID
```

### 問題5: Cloud Run Service削除エラー

**症状**: `Error: cannot destroy service without setting deletion_protection=false`

**原因**: 削除保護が有効

**解決策**: 手動で削除してから再デプロイ

```bash
gcloud run services delete SERVICE_NAME --region=$REGION --quiet
terraform apply -auto-approve
```

### 問題6: Pub/Sub subscriptionエラー（iam.serviceAccounts.actAs）

**症状**: `Error 403: Principal initiating the request does not have iam.serviceAccounts.actAs permission`

**原因**: 設計上の問題（既に修正済み）

**解決策**: `terraform/modules/pubsub/main.tf`で確認

```hcl
# 正しい設定（batch-worker-saを使用）
push_config {
  push_endpoint = var.batch_worker_url
  oidc_token {
    service_account_email = var.pubsub_service_account_email  # batch-worker-sa
  }
}
```

### 問題7: API有効化エラー

**症状**: `Error 403: ... API is not enabled`

**原因**: 必要なAPIが有効化されていない

**解決策**: APIを有効化

```bash
# 個別に有効化
gcloud services enable SERVICE_NAME.googleapis.com

# または全APIを再有効化（Phase 1のステップ1-2を再実行）
```

### 問題8: impersonation権限エラー

**症状**: `Error: google: could not find default credentials`

**原因**: Editor権限者にimpersonation権限が付与されていない

**解決策**: Owner権限者に依頼して権限を付与

```bash
# Owner権限者が実行
gcloud iam service-accounts add-iam-policy-binding \
  terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com \
  --member="user:EDITOR_EMAIL" \
  --role="roles/iam.serviceAccountTokenCreator"
```

---

## トラブルシューティングフローチャート

```
エラー発生
    │
    ├─ Dockerビルド時 → 問題1を確認
    ├─ Terraform init時 → backend.tfのバケット名を確認
    ├─ Terraform plan/apply時
    │   ├─ VPC Connector関連 → 問題2,3を確認
    │   ├─ State lock → 問題4を確認
    │   ├─ deletion_protection → 問題5を確認
    │   ├─ Pub/Sub subscription → 問題6を確認
    │   └─ API not enabled → 問題7を確認
    └─ 認証エラー → 問題8を確認
```

---

## 付録: 完全なコマンドチートシート

### Owner権限者用

```bash
# 環境変数設定
export PROJECT_ID="your-project-id"
export REGION="asia-northeast1"
export EDITOR_EMAIL="editor@example.com"
gcloud config set project $PROJECT_ID

# API有効化
gcloud services enable compute.googleapis.com run.googleapis.com pubsub.googleapis.com redis.googleapis.com storage.googleapis.com secretmanager.googleapis.com vpcaccess.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

# State用バケット作成
gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://${PROJECT_ID}-tfstate
gsutil versioning set on gs://${PROJECT_ID}-tfstate

# terraform-sa作成
gcloud iam service-accounts create terraform-sa --display-name="Terraform Service Account for Infrastructure Management"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/editor"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/iam.serviceAccountUser"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/secretmanager.admin"
gcloud iam service-accounts add-iam-policy-binding terraform-sa@${PROJECT_ID}.iam.gserviceaccount.com --member="user:${EDITOR_EMAIL}" --role="roles/iam.serviceAccountTokenCreator"

# streamlit-sa作成
gcloud iam service-accounts create streamlit-sa --display-name="Streamlit Frontend Service Account"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/pubsub.publisher"
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:streamlit-sa@${PROJECT_ID}.iam.gserviceaccount.com" --role="roles/run.invoker"

# batch-worker-sa作成
gcloud iam service-accounts create batch-worker-sa --display-name="Batch Worker Service Account"

# 確認
gcloud iam service-accounts list --filter="email:*-sa@${PROJECT_ID}.iam.gserviceaccount.com"
```

### Editor権限者用

```bash
# 環境変数設定
export PROJECT_ID="your-project-id"
export REGION="asia-northeast1"
gcloud config set project $PROJECT_ID

# Artifact Registry作成
gcloud artifacts repositories create docker-repo --repository-format=docker --location=$REGION
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Dockerビルド（Streamlit）
cd apps/streamlit-app
docker buildx build --platform linux/amd64 -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest --load .
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/streamlit-app:latest

# Dockerビルド（Batch Worker）
cd ../batch-worker
docker buildx build --platform linux/amd64 -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest --load .
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/docker-repo/batch-worker:latest

# Terraform実行
cd ../../terraform
# terraform.tfvarsを編集
terraform init
terraform plan
terraform apply -auto-approve
terraform output

# 動作確認
export STREAMLIT_URL=$(terraform output -raw streamlit_url)
open $STREAMLIT_URL
gcloud pubsub topics publish pdf-processing-topic --message='{"job_id": "test-001", "pdf_path": "test.pdf"}'
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=batch-worker-service" --limit=20
```

---

**最終確認**: 全ての手順が完了し、動作確認が成功したら、デプロイ完了です！🎉
