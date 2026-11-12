data "aws_caller_identity" "current" {}

locals {
  bucket_name = var.bucket_name != "" ? var.bucket_name : "nirvaah-backups-${data.aws_caller_identity.current.account_id}"
  prefix      = trim(var.backup_prefix, "/")

  tags = {
    Project   = "nirvaah"
    Component = "backups"
    ManagedBy = "terraform"
  }
}

resource "aws_s3_bucket" "backups" {
  bucket = local.bucket_name

  # Object Lock is a creation-time property: enabling it later needs a new bucket.
  object_lock_enabled = var.object_lock_enabled

  force_destroy = false # a destroyed bucket must never take the backups with it
}

# ACLs off: ownership always belongs to the bucket owner, so no grant can leak data.
resource "aws_s3_bucket_ownership_controls" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# The single most important control for a backup bucket.
resource "aws_s3_bucket_public_access_block" "backups" {
  bucket = aws_s3_bucket.backups.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != "" ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn != "" ? var.kms_key_arn : null
    }
    bucket_key_enabled = var.kms_key_arn != "" ? true : null
  }
}

resource "aws_s3_bucket_object_lock_configuration" "backups" {
  count  = var.object_lock_enabled ? 1 : 0
  bucket = aws_s3_bucket.backups.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.object_lock_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.backups]
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "expire-superseded-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = var.abort_incomplete_days
    }
  }

  dynamic "rule" {
    for_each = var.archive_after_days > 0 ? [1] : []

    content {
      id     = "archive-old-backups"
      status = "Enabled"

      filter {}

      transition {
        days          = var.archive_after_days
        storage_class = "STANDARD_IA"
      }

      transition {
        days          = 90
        storage_class = "GLACIER_IR"
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.backups]
}

data "aws_iam_policy_document" "backups" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.backups.arn,
      "${aws_s3_bucket.backups.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Note: no "deny if the SSE header is missing" statement on purpose. The
  # bucket has default encryption (AES256), so every object is encrypted at
  # rest whether or not the client sends the header — while a hard deny breaks
  # ordinary clients (aws-cli v1 among them) that rely on that default.

  # Only bucket *deletion* is denied. Denying PutBucketPolicy here would also
  # block the IAM principal that runs Terraform (an explicit deny applies to
  # admins too; only the root user bypasses it), so the policy stays editable
  # by IaC while the bucket itself cannot be removed out from under the backups.
  statement {
    sid    = "DenyBucketDeletion"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:DeleteBucket"]

    resources = [aws_s3_bucket.backups.arn]
  }
}

resource "aws_s3_bucket_policy" "backups" {
  bucket = aws_s3_bucket.backups.id
  policy = data.aws_iam_policy_document.backups.json

  depends_on = [aws_s3_bucket_public_access_block.backups]
}
