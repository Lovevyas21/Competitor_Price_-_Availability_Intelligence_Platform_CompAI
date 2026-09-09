# Lookups into the persistent stack.
#
# Data sources rather than `terraform_remote_state`: every one of these is addressed by
# a name this stack already derives from `var.project`, so the two stacks stay decoupled
# and neither needs a remote backend to find the other. The cost of that choice is that
# `project` and `environment` must match across both -- which the README says and the
# names make obvious when they do not.

data "aws_caller_identity" "current" {}

data "aws_s3_bucket" "bronze" {
  bucket = "${var.project}-bronze-${data.aws_caller_identity.current.account_id}"
}

data "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

# The image repository, created by the persistent stack.
data "aws_ecr_repository" "app" {
  name = var.project
}
