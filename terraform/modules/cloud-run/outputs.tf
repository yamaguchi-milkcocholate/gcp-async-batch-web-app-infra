output "service_url" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_v2_service.streamlit.uri
}

output "service_name" {
  description = "Cloud Run service name"
  value       = google_cloud_run_v2_service.streamlit.name
}
