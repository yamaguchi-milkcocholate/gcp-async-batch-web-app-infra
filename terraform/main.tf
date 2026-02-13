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
  batch_worker_url             = module.cloud_run_worker.service_url
  pubsub_service_account_email = data.google_service_account.batch_worker.email

  depends_on = [module.cloud_run_worker]
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
  project_number        = var.project_number

  depends_on = [module.vpc, module.redis, module.storage]
}
