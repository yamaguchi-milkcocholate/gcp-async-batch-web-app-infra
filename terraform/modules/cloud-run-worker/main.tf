resource "google_cloud_run_v2_service" "batch_worker" {
  name     = var.service_name
  location = var.region

  template {
    containers {
      image = var.container_image

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
          cpu    = "2"
          memory = "2Gi"
        }
      }
    }

    timeout         = "1800s" # 30分
    service_account = var.service_account_email

    # VPC Connector経由でRedisに接続
    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    # スケーリング設定
    scaling {
      min_instance_count = 0 # アイドル時はインスタンス0（コスト削減）
      max_instance_count = 3 # 最大3インスタンス（並列処理）
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
