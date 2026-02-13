variable "service_name" {
  description = "Cloud Run service name"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "container_image" {
  description = "Container image URL"
  type        = string
}

variable "service_account_email" {
  description = "Service account email"
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

variable "redis_host_secret_id" {
  description = "Redis host secret ID"
  type        = string
}

variable "vpc_connector_id" {
  description = "VPC connector ID"
  type        = string
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}
