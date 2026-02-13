output "topic_id" {
  description = "Pub/Sub topic ID"
  value       = google_pubsub_topic.pdf_processing.id
}

output "topic_name" {
  description = "Pub/Sub topic name"
  value       = google_pubsub_topic.pdf_processing.name
}

output "subscription_id" {
  description = "Pub/Sub subscription ID"
  value       = google_pubsub_subscription.pdf_processing_sub.id
}

output "subscription_name" {
  description = "Pub/Sub subscription name"
  value       = google_pubsub_subscription.pdf_processing_sub.name
}
