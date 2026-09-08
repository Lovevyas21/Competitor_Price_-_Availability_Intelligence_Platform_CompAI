# The account id is part of the bronze bucket name: S3 bucket names are globally unique
# across every AWS account, so a bare "cpi-bronze" would collide with a stranger's.
data "aws_caller_identity" "current" {}
