data "aws_caller_identity" "current" {}

data "aws_s3_bucket" "bronze" {
  bucket = "${var.project}-bronze-${data.aws_caller_identity.current.account_id}"
}

data "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

data "aws_ecr_repository" "app" {
  name = var.project
}
