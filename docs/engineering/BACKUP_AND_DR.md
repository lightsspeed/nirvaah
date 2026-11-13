# Backup and disaster recovery

The backup container is a long-running shell script (`backup/backup.sh`) with two
entrypoints: it dumps PostgreSQL on an interval, verifies the dump by restoring
it, uploads it to S3-compatible storage, and reads the object back before calling
the run a success. `backup/restore.sh` is the other half: it verifies an archive's
checksum and restores it into a scratch database.

```
pg_dump --format=custom
      │
      ├─ archive readable?            pg_restore --list
      ├─ SHA-256 sidecar written     <file>.sha256
      ├─ restores into a scratch DB  nirvaah_verify, all public tables compared
      │
      ├─ unchanged since last verified dump? → stop here, status "unchanged"
      │
      ├─ copy to latest.dump
      ├─ upload with metadata sha256=<hex>
      ├─ head-object: size + metadata checksum match?
      ├─ download the object and hash it locally?
      │
      ├─ verified: true → status "ok" → retention may run
      └─ anything else → status "dump-failed" / "verify-failed" / "upload-failed"
                         → retention suspended, last_success untouched
```

## What a run guarantees

A run reports `ok` only when all of the following held:

| Step | Check |
|---|---|
| dump | `pg_dump --format=custom --compress=9 --no-owner --no-privileges` exited 0 and the archive lists cleanly |
| local integrity | `sha256sum` recorded in `<archive>.sha256` beside the archive |
| restorability | the archive was restored into `nirvaah_verify`; **every** public table then matched the live database's row count and per-table md5 fingerprint |
| upload | `aws s3 cp` returned 0, `head-object` reported the same byte size, the `sha256` metadata matched, and the object was downloaded again and hashed to the same digest |

`verified: true` is written to `state/status.json` and `state/last_success.json`
only after the remote read-back succeeds. Nothing else sets it.

## State files

`state/status.json` describes the **latest run**:

```json
{
  "status": "upload-failed",
  "last_run": "2026-11-13T03:39:23Z",
  "last_run_ok": false,
  "verified": false,
  "last_dump": "20261112T092758Z",
  "bytes": 0,
  "last_success": { "at": "...", "file": "...", "remote": "...", "sha256": "...", "bytes": 48579, "remote_verified": true }
}
```

- `last_run` / `status` / `last_run_ok` describe the newest attempt, including
  failures. The healthcheck reads these, so a dead access key turns the container
  unhealthy even while an older successful backup is still on disk.
- `last_success` is the newest **verified** backup. A failed run never overwrites
  or clears it, so the last known good copy is always identifiable.
- `state/last_success.json` holds the same `last_success` object on its own, which
  is what retention and `--verify-remote` read.

`--health` is what the container healthcheck runs. It fails when the newest run
did not end in `ok`/`unchanged`, and also when the newest completed run is older
than twice `INTERVAL_HOURS` — a stale success must not read as a healthy agent.
(Checking `--status` text for "ok" was wrong: the substring also appears in
`"last_run_ok":false`.)

## Retention

Retention runs only after a run reports `ok` — a run with nothing new to protect
must not delete anything, and a failing run deletes nothing at all:

- local and remote archives older than `BACKUP_RETENTION_DAYS` are pruned, except
  archives dated the 1st of a month;
- the newest `BACKUP_RETENTION_MONTHS` first-of-month archives are kept;
- the latest verified archive, `latest.dump`, its sidecar and the newest remote
  object are never pruned, whatever their age.

## Locking

`state/backup.lock` is a directory created with `mkdir` (atomic). The owner file
records PID, the process start time from `/proc/<pid>/stat` and the hostname.

- Same host: the PID must be alive **and** the start time must match, so a
  recycled PID is not mistaken for the running backup.
- Another container on the same volume: the holder refreshes
  `state/backup.lock/heartbeat` while it runs; the lock counts as abandoned only
  once that heartbeat is older than `LOCK_STALE_MINUTES` (default 30).
- A lock with no owner file is only cleared once it is older than two minutes.
- The lock is released on normal exit and on handled failures (EXIT trap).

A second run that cannot take the lock logs `another backup is running` and exits
0 — that is not a failure, so the interval loop keeps its schedule.

## Restore

```bash
# list what exists, locally and remotely
docker compose run --rm --entrypoint /backup/restore.sh backup --list

# verify the checksum and restore into a scratch database (default target)
docker compose run --rm --entrypoint /backup/restore.sh backup --file latest.dump

# restore over the live database — requires the explicit flag
docker compose run --rm --entrypoint /backup/restore.sh backup --file latest.dump --into-live
```

Safety rules, in the order the script applies them:

1. The archive's SHA-256 is verified before `pg_restore` runs, from the sidecar or,
   for a downloaded object, from the `sha256` object metadata. A mismatch — or no
   checksum at all — refuses by default.
2. `--force` overrides *only* that refusal. It never bypasses a target check.
3. The archive must list cleanly (`pg_restore --list`) even with `--force`, so a
   truncated file cannot be half-restored.
4. Restoring into the live database requires `--into-live`. The scratch target can
   never be the live database name, and the system databases are refused outright.

After a scratch restore, swap the databases by renaming once the row counts look
right — the script prints the two `ALTER DATABASE` statements to run.

## Permissions

The backup identity needs, on the bucket and its prefix only:

| Action | Why |
|---|---|
| `s3:PutObject`, `s3:PutObjectTagging` | upload |
| `s3:GetObject`, `s3:GetObjectTagging`, `s3:GetObjectVersion` | read-back verification, restore download |
| `s3:DeleteObject` | retention |
| `s3:ListBucket`, `s3:GetBucketLocation` | retention and `--list` |

No `s3:DeleteBucket`, no bucket-level `s3:*`, no IAM actions. Credentials arrive
as environment variables only (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`);
there is no credentials-file path in the container.

## Tests

`backup/tests/test-backup.sh` runs the real entrypoints against a disposable
Postgres and an S3-compatible server on their own Docker network:

```bash
bash backup/tests/test-backup.sh
```

Covered: successful verified backup; on-demand offsite verification; restore into
a scratch database; checksum mismatch refusal; truncated archive refusal (also
with `--force`); live-target refusal without `--into-live`; rejected credentials;
unreachable endpoint; remote object tampering; retention after success; retention
suspended after failure; monthly archive retention; lock contention and stale-lock
reclaim; verification database and lock cleanup.

What the tests prove and what they do not:

| Category | Status |
|---|---|
| Real PostgreSQL dump, restore, all-table verification | exercised |
| Real S3 API (put with metadata, head-object, get, list, delete) | exercised against `adobe/s3mock` |
| MinIO | not used — its images are no longer pullable from this environment |
| 403 `InvalidAccessKeyId` | **simulated** by `backup/tests/s3_denied.py` |
| Real AWS bucket, real IAM policy, object lock, lifecycle | **unverified** — the key in `.env` no longer exists in AWS |
