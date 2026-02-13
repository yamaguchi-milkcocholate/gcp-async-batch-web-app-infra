output "redis_host" {
  description = "Redis instance host IP"
  value       = google_redis_instance.redis.host
}

output "redis_port" {
  description = "Redis instance port"
  value       = google_redis_instance.redis.port
}

output "redis_host_secret_id" {
  description = "Secret Manager secret ID for Redis host"
  value       = google_secret_manager_secret.redis_host.secret_id
}
