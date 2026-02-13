variable "redis_instance_name" {
  description = "Redis instance name"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "vpc_id" {
  description = "VPC network ID"
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
