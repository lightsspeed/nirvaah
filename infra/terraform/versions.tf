terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Local state is fine for a single-operator stack. If you ever add a second
  # person or machine, move this to an S3 backend with locking:
  #
  # backend "s3" {
  #   bucket       = "your-tf-state-bucket"
  #   key          = "nirvaah/backups.tfstate"
  #   region       = "ap-south-1"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}
