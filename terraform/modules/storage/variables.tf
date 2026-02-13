variable "bucket_name" {
  description = "GCS bucket name"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "streamlit_sa_email" {
  description = "Streamlit service account email"
  type        = string
}

variable "batch_worker_sa_email" {
  description = "Batch worker service account email"
  type        = string
}
