resource "google_pubsub_topic" "pdf_processing" {
  name = var.topic_name

  message_retention_duration = "86400s" # 1日間保持

  labels = {
    environment = var.environment
  }
}

resource "google_pubsub_subscription" "pdf_processing_sub" {
  name  = var.subscription_name
  topic = google_pubsub_topic.pdf_processing.id

  ack_deadline_seconds = 600 # 10分（長時間処理対応）

  message_retention_duration = "86400s" # 1日間

  # Push設定（Cloud Run Serviceに配信）
  push_config {
    push_endpoint = var.batch_worker_url

    oidc_token {
      service_account_email = var.pubsub_service_account_email
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  labels = {
    environment = var.environment
  }
}
