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
  name          = "pdf-vpc-connector"
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.0.2.0/28"

  # スループット設定
  min_instances = 2            # 最小インスタンス数（GCPの制約: 最低2）
  max_instances = 3            # 最大インスタンス数（負荷に応じて自動スケール）
  machine_type  = "e2-micro"   # 最小インスタンスタイプ
}

# Redisへのイングレスファイアウォールルール
resource "google_compute_firewall" "redis_ingress" {
  name    = "${var.vpc_name}-allow-redis"
  network = google_compute_network.vpc.name

  allow {
    protocol = "tcp"
    ports    = ["6379"]
  }

  source_ranges = ["10.0.2.0/28"] # VPC Connectorからのアクセスのみ許可
}
