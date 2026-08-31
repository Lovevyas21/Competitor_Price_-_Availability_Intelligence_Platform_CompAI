# S3 bronze layer: every raw API payload, before parsing.
#
# This bucket is the reason losing the database is survivable -- the warehouse is
# rebuilt from it with `cpi replay`, no upstream traffic and no quota spend.

resource "aws_s3_bucket" "bronze" {
  bucket = "${var.project}-bronze-${data.aws_caller_identity.current.account_id}"

  tags = { Name = "${var.project}-bronze" }
}

resource "aws_s3_bucket_public_access_block" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning protects the audit trail from an accidental overwrite of a raw payload.
resource "aws_s3_bucket_versioning" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  # Raw JSON is written once and read rarely -- only on replay. Tiering it keeps the
  # bill flat as history accumulates.
  rule {
    id     = "tier-old-payloads"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER_IR"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "expire-dead-letters"
    status = "Enabled"

    filter {
      prefix = "deadletter/"
    }

    # Dead letters are for debugging; keeping them for a year has no value.
    expiration {
      days = 90
    }
  }

  depends_on = [aws_s3_bucket_versioning.bronze]
}
