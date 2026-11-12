output "bucket" {
  description = "Bucket name — put this in .env as S3_BUCKET"
  value       = aws_s3_bucket.backups.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.backups.arn
}

output "region" {
  description = "Put this in .env as AWS_REGION"
  value       = var.region
}

output "s3_prefix" {
  description = "Put this in .env as S3_PREFIX"
  value       = local.prefix
}

output "object_lock_mode" {
  value = var.object_lock_enabled ? "GOVERNANCE/${var.object_lock_days}d" : "disabled"
}

output "backup_agent_user" {
  description = "IAM user the backup container authenticates as"
  value       = var.create_backup_agent_user ? aws_iam_user.backup_agent[0].name : null
}

output "backup_agent_access_key_id" {
  description = "Only set when create_access_key = true"
  value       = var.create_access_key && var.create_backup_agent_user ? aws_iam_access_key.backup_agent[0].id : null
}

output "backup_agent_secret_access_key" {
  description = "Only set when create_access_key = true. Stored in state, so prefer a key made outside Terraform."
  value       = var.create_access_key && var.create_backup_agent_user ? aws_iam_access_key.backup_agent[0].secret : null
  sensitive   = true
}

output "env_block" {
  description = "Paste-ready block for .env; the secret is whatever you put in AWS_SECRET_ACCESS_KEY"
  value       = <<-EOT
    S3_BUCKET=${aws_s3_bucket.backups.bucket}
    S3_PREFIX=${local.prefix}
    AWS_REGION=${var.region}
    AWS_ACCESS_KEY_ID=<your access key id>
    AWS_SECRET_ACCESS_KEY=<your secret access key>
  EOT
}
