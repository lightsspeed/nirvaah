variable "region" {
  description = "AWS region for the backup bucket. Pick the one closest to where the app runs."
  type        = string
  default     = "ap-south-1"
}

variable "bucket_name" {
  description = "Globally unique bucket name. Empty means nirvaah-backups-<account-id>."
  type        = string
  default     = ""
}

variable "backup_prefix" {
  description = "Key prefix the backup agent writes under. Also the IAM policy scope."
  type        = string
  default     = "nirvaah/postgres"
}

variable "object_lock_enabled" {
  description = "Enable S3 Object Lock (must be decided at creation, cannot be added later)."
  type        = bool
  default     = true
}

variable "object_lock_days" {
  description = "GOVERNANCE-mode retention. Keep this below the agent's prune window so normal retention still works."
  type        = number
  default     = 7

  validation {
    condition     = var.object_lock_days >= 1 && var.object_lock_days <= 365
    error_message = "object_lock_days must be between 1 and 365."
  }
}

variable "noncurrent_version_days" {
  description = "How long to keep superseded object versions after the current one is deleted."
  type        = number
  default     = 30
}

variable "archive_after_days" {
  description = "Move objects to a cheaper storage class after this many days (0 disables)."
  type        = number
  default     = 30
}

variable "abort_incomplete_days" {
  description = "Abort multipart uploads that never finished."
  type        = number
  default     = 7
}

variable "kms_key_arn" {
  description = "Optional KMS key for SSE-KMS. Empty uses SSE-S3 (AES256), which is free and sufficient for a private backup bucket."
  type        = string
  default     = ""
}

variable "create_backup_agent_user" {
  description = "Create a least-privilege IAM user + access key for the backup container."
  type        = bool
  default     = true
}

variable "create_access_key" {
  description = <<-EOT
    Create an access key for the backup agent. Off by default: keys created here
    are stored in Terraform state in plaintext, and rotating one is easier than
    rotating a secret that lives in state. Create the key once (console or
    `aws iam create-access-key`) and put it in .env instead.
  EOT
  type        = bool
  default     = false
}

variable "operator_cidr_allowed" {
  description = "Optional CIDR allowed to read the bucket outside the IAM user (empty = nobody extra)."
  type        = string
  default     = ""
}
