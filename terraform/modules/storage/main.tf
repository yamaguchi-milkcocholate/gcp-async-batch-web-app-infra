resource "google_storage_bucket" "pdf_storage" {
  name          = var.bucket_name
  location      = var.region
  storage_class = "STANDARD"

  uniform_bucket_level_access = true

  # 24時間TTL: 1日経過したファイルを自動削除
  lifecycle_rule {
    condition {
      age = 1 # 1日
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
