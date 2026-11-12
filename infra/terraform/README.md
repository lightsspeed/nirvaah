# Backup bucket (Terraform)

Creates the S3 bucket the `backup` container ships Postgres dumps to, plus a
least-privilege IAM identity for that container. Everything is private by
default and stays that way.

## What gets created

| Resource | Why |
|---|---|
| `aws_s3_bucket` | container for the dumps; `force_destroy = false` so `terraform destroy` cannot silently take the backups with it |
| `aws_s3_bucket_public_access_block` | all four switches on — the single most important control |
| `aws_s3_bucket_ownership_controls` | ACLs disabled; the bucket owner always owns the objects |
| `aws_s3_bucket_versioning` | overwrites and deletes keep the previous bytes |
| `aws_s3_bucket_server_side_encryption_configuration` | AES256 by default; set `kms_key_arn` for SSE-KMS |
| `aws_s3_bucket_object_lock_configuration` | GOVERNANCE mode, 7 days — a compromised key cannot erase the last week |
| `aws_s3_bucket_lifecycle_configuration` | superseded versions expire in 30 days, objects move to STANDARD_IA then GLACIER_IR, half-finished multipart uploads abort |
| `aws_s3_bucket_policy` | denies non-TLS access, denies `DeleteBucket`/`PutBucketPolicy` |
| `aws_iam_user` + policy + access key | write/read/list/prune under `nirvaah/postgres/` only — no version deletion, no bucket changes |

Object Lock is set at creation time and cannot be added later; `object_lock_days`
is deliberately shorter than the agent's prune window (14 days) so normal
retention still works.

## Use

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply

# wire it into the app
terraform output env_block                 # paste into ../../.env
terraform output -raw backup_agent_secret_access_key   # the secret, once
```

Then recreate the backup service so it picks up the credentials:

```bash
cd ../..
docker compose up -d backup
docker compose run --rm backup --once      # expect: upload complete
```

## Verify

```bash
B=$(terraform output -raw bucket)
aws s3api get-public-access-block   --bucket "$B"
aws s3api get-bucket-versioning     --bucket "$B"
aws s3api get-bucket-encryption     --bucket "$B"
aws s3api get-object-lock-configuration --bucket "$B"
aws s3 ls "s3://$B/nirvaah/postgres/"
```

## Notes

- State holds the IAM secret in plaintext. It is git-ignored; if that matters
  to you, move to an encrypted S3 backend (template in `versions.tf`) or use
  `terraform output -raw …` once and delete the key resource afterwards.
- The bucket name defaults to `nirvaah-backups-<account-id>`; override with
  `-var bucket_name=…` — it has to be globally unique.
- Prefer Cloudflare R2 or Backblaze B2 if egress cost matters: both work with
  this compose stack via `S3_ENDPOINT`, and R2 charges nothing for egress.
- The backup container sits on a dedicated `egress` network. The rest of the
  stack stays on internal networks and cannot reach the internet at all.
