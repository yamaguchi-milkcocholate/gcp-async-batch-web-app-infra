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
  tier               = "BASIC" # 試験運用のためBASIC tierを使用
  memory_size_gb     = 1
  region             = var.region
  authorized_network = var.vpc_id

  redis_version = "REDIS_7_0"
  display_name  = "PDF Processing Status Store"

  # セキュリティ: TLS無効（試験運用のためコスト優先）
  transit_encryption_mode = "DISABLED"

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
