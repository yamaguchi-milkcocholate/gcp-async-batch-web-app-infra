output "streamlit_url" {
  description = "Streamlit Cloud Run service URL"
  value       = module.cloud_run.service_url
}

output "batch_worker_url" {
  description = "Batch Worker Cloud Run service URL"
  value       = module.cloud_run_worker.service_url
}

output "gcs_bucket_name" {
  description = "GCS bucket name"
  value       = module.storage.bucket_name
}

output "redis_host" {
  description = "Redis instance host IP"
  value       = module.redis.redis_host
}

output "pubsub_topic" {
  description = "Pub/Sub topic full path"
  value       = module.pubsub.topic_id
}

output "redis_secret_id" {
  description = "Redis host Secret Manager ID"
  value       = module.redis.redis_host_secret_id
}

output "vpc_connector_id" {
  description = "VPC Access Connector ID"
  value       = module.vpc.vpc_connector_id
}
