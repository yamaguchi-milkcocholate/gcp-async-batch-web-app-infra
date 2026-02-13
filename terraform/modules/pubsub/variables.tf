variable "topic_name" {
  description = "Pub/Sub topic name"
  type        = string
}

variable "subscription_name" {
  description = "Pub/Sub subscription name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "batch_worker_url" {
  description = "Batch Worker Cloud Run Service URL for Push subscription"
  type        = string
}

variable "pubsub_service_account_email" {
  description = "Pub/Sub service account email"
  type        = string
}
