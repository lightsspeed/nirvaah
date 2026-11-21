terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Local state is fine for one operator. Move to S3 before a second machine
  # touches this stack:
  #
  # backend "s3" {
  #   bucket       = "your-tf-state-bucket"
  #   key          = "nirvaah/app.tfstate"
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
