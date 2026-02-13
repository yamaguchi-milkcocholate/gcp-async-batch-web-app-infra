terraform {
  backend "gcs" {
    bucket = "weekly-dev-20251013-tfstate"
    prefix = "terraform/state"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.18.0"
    }
  }

  required_version = ">= 1.9.0"
}
