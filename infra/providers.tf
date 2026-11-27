terraform {
  required_version = ">= 1.0"

  required_providers {
    huaweicloud = {
      source  = "huaweicloud/huaweicloud"
      version = ">= 1.79.0"
    }
  }
}

# Credentials are supplied via environment variables (HW_ACCESS_KEY /
# HW_SECRET_KEY) or via the provider's default credential chain.
# Real keys are NEVER written into this repository.
provider "huaweicloud" {
  region = var.region
  # IAM is a global service; the regional IAM endpoint
  # (iam.<region>.myhuaweicloud.com) lacks the full service-principal
  # domain catalog, so agency creation fails with "Could not find domain".
  # Point IAM at the global endpoint where service domains are registered.
  endpoints = {
    iam = "https://iam.myhuaweicloud.com"
  }
}
