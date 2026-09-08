terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State is local by default so this configuration can be validated with no AWS
  # account. Before a real apply, move it to S3 + DynamoDB locking by uncommenting
  # below -- local state on a laptop is not a place to keep infrastructure of record.
  #
  # backend "s3" {
  #   bucket         = "cpi-tfstate"
  #   key            = "cpi/ephemeral.tfstate"
  #   region         = "ap-south-1"
  #   dynamodb_table = "cpi-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
