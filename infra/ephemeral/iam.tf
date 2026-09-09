# Least privilege: the instance role may read this project's parameters and write to
# this project's bucket. Nothing else -- no wildcard resources anywhere.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project}-app-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = { Name = "${var.project}-app-role" }
}

data "aws_iam_policy_document" "app" {
  # Bronze: read and write objects, but never delete them and never reconfigure the
  # bucket. Bronze is the audit trail and the disaster-recovery source; the application
  # has no business removing from it.
  statement {
    sid       = "BronzeObjectAccess"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${data.aws_s3_bucket.bronze.arn}/*"]
  }

  statement {
    sid       = "BronzeList"
    actions   = ["s3:ListBucket"]
    resources = [data.aws_s3_bucket.bronze.arn]
  }

  # Only this project's parameters, in this environment.
  #
  # Two ARNs, not one, and the difference is not cosmetic. `GetParameter` acts on each
  # parameter, so it needs `/cpi/prod/*`. `GetParametersByPath` acts on the *path node*
  # `/cpi/prod` itself, which `/cpi/prod/*` does not match -- a trailing wildcard covers
  # the children, never the parent. Granting only the wildcard produces an AccessDenied
  # naming a resource that looks like it is obviously covered.
  statement {
    sid     = "ReadOwnParameters"
    actions = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project}/${var.environment}",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project}/${var.environment}/*",
    ]
  }

  statement {
    sid       = "DecryptParameters"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }

  # ECR. Split across two statements because `GetAuthorizationToken` is an account-level
  # action that AWS only accepts against `*` -- scoping it to the repository silently
  # denies every login. Everything that touches image content is scoped to this one
  # repository.
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPushPull"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [data.aws_ecr_repository.app.arn]
  }

  statement {
    sid = "WriteOwnLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.project}-app-policy"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

# SSM Session Manager gives shell access with no SSH port and no key material.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project}-app-profile"
  role = aws_iam_role.app.name
}
