variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "project_number" {
  description = "GCP Project Number (for Pub/Sub service account)"
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
