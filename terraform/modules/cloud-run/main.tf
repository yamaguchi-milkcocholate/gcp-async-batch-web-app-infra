resource "google_cloud_run_v2_service" "streamlit" {
  name               = var.service_name
  location           = var.region
  deletion_protection = false

  template {
    containers {
      image = var.container_image

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
            version = "latest" # 本番運用では "1" など特定バージョンを指定推奨
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
