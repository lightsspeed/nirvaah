# Least privilege for the backup container: it can write, read back, list and
# add delete markers under its own prefix. It cannot delete versions, change the
# bucket, or touch anything outside the prefix.

data "aws_iam_policy_document" "backup_agent" {
  statement {
    sid       = "ListOwnPrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.backups.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${local.prefix}/*", local.prefix]
    }
  }

  statement {
    sid    = "ReadWriteOwnPrefix"
    effect = "Allow"

    actions = [
      "s3:PutObject",
      "s3:PutObjectTagging",
      "s3:GetObject",
      "s3:GetObjectTagging",
      "s3:GetObjectVersion",
    ]

    resources = ["${aws_s3_bucket.backups.arn}/${local.prefix}/*"]
  }

  # Pruning writes a delete marker; the object itself stays recoverable.
  statement {
    sid       = "PruneWithDeleteMarkers"
    effect    = "Allow"
    actions   = ["s3:DeleteObject"]
    resources = ["${aws_s3_bucket.backups.arn}/${local.prefix}/*"]
  }
}

resource "aws_iam_policy" "backup_agent" {
  name        = "${local.bucket_name}-backup-agent"
  description = "Write/read/restore access for the Nirvaah backup container, scoped to ${local.prefix}"

  policy = data.aws_iam_policy_document.backup_agent.json
}

resource "aws_iam_user" "backup_agent" {
  count = var.create_backup_agent_user ? 1 : 0

  name = "nirvaah-backup-agent"

  # No console login: this identity is only usable with an access key.
  path = "/service/"
}

resource "aws_iam_user_policy_attachment" "backup_agent" {
  count = var.create_backup_agent_user ? 1 : 0

  user       = aws_iam_user.backup_agent[0].name
  policy_arn = aws_iam_policy.backup_agent.arn
}

resource "aws_iam_access_key" "backup_agent" {
  count = var.create_backup_agent_user && var.create_access_key ? 1 : 0

  user = aws_iam_user.backup_agent[0].name
}
