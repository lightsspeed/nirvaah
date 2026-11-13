#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Disposable backup/restore tests: real PostgreSQL, real S3 API (s3mock), no AWS.
#
#   bash backup/tests/test-backup.sh
#
# Builds the backup image, starts a throwaway Postgres and an S3-compatible server
# on their own network, and drives the real entrypoints through success and
# failure. MinIO was the first choice but its images are no longer pullable from
# this environment; adobe/s3mock speaks the same API surface we use (put with
# metadata, head-object, list, get, delete). The "dead access key" path is served
# by a small stub that returns the exact S3 403, and is labelled as simulated.
#
# Nothing here touches the production stack, its volumes, or AWS.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

RUN_ID="$$"
IMG="${IMG:-nirvaah-backup:test20}"
NET="t20net-$RUN_ID"
DB="t20-db-$RUN_ID"
S3="t20-s3-$RUN_ID"
DENIED="t20-denied-$RUN_ID"
WORK="t20work-$RUN_ID"
STATE="t20state-$RUN_ID"
BUCKET="nirvaah-backup-test"
PGPASS="t20-disposable-pass"
S3_KEY="s3mock-key"
S3_SECRET="s3mock-secret"
PY_IMAGE="python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b"

PG_IMAGE="postgres:16-alpine@sha256:f377d590e5474681d4d7838635031a2b50647923b7abfa803ce9b5ff35d5c663"
S3_IMAGE="${S3_IMAGE:-adobe/s3mock:latest}"
HERE="$(cd "$(dirname "$0")" && pwd)"

pass=0
fail=0
ok()   { pass=$((pass + 1)); printf 'PASS  %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf 'FAIL  %s%s\n' "$1" "${2:+ — $2}"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$2], got [$3]"; fi; }
contains() { case "$3" in *"$2"*) ok "$1" ;; *) bad "$1" "missing [$2] in ${3:0:200}" ;; esac; }

cleanup() {
    docker rm -f "$DB" "$S3" "$DENIED" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    docker volume rm "$WORK" "$STATE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for f in backup/backup.sh backup/restore.sh; do
    if grep -q $'\r' "$f"; then echo "CRLF line endings in $f — cannot run in the container"; exit 1; fi
done
echo "▶ building $IMG"
docker build -q -t "$IMG" backup >/dev/null || { echo "image build failed"; exit 1; }

cleanup
docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" -e POSTGRES_USER=finance -e POSTGRES_PASSWORD="$PGPASS" \
    -e POSTGRES_DB=finance "$PG_IMAGE" >/dev/null
docker run -d --name "$S3" --network "$NET" -e initialBuckets="$BUCKET" "$S3_IMAGE" >/dev/null
docker run -d --name "$DENIED" --network "$NET" -v "$HERE/s3_denied.py:/denied.py:ro" \
    "$PY_IMAGE" python /denied.py >/dev/null

for _ in $(seq 1 60); do docker exec "$DB" pg_isready -U finance -d finance >/dev/null 2>&1 && break; sleep 1; done
for _ in $(seq 1 60); do
    docker run --rm --network "$NET" -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
        -e AWS_DEFAULT_REGION=us-east-1 --entrypoint sh "$IMG" \
        -c "aws --endpoint-url http://$S3:9090 s3 ls >/dev/null 2>&1" && break
    sleep 1
done
docker run --rm --network "$NET" -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
    -e AWS_DEFAULT_REGION=us-east-1 --entrypoint sh "$IMG" \
    -c "aws --endpoint-url http://$S3:9090 s3 mb s3://$BUCKET >/dev/null 2>&1 || true"

seed_db() {
    docker exec -i "$DB" psql -U finance -d finance -q <<'SQL'
CREATE TABLE IF NOT EXISTS alpha (id int primary key, label text);
CREATE TABLE IF NOT EXISTS beta  (id int primary key, label text);
CREATE TABLE IF NOT EXISTS gamma (id int primary key, label text);
INSERT INTO alpha VALUES (1,'a'),(2,'b');
INSERT INTO beta  VALUES (1,'b');
INSERT INTO gamma VALUES (1,'g'),(2,'h'),(3,'i');
SQL
}
seed_db
for c in "$DB" "$S3" "$DENIED"; do
    if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" != "true" ]; then
        echo "infrastructure container $c is not running; aborting"; docker logs "$c" 2>&1 | tail -5; exit 1
    fi
done

backup_run() { # backup_run <endpoint> [retention_days]
    docker run --rm --network "$NET" -v "$WORK:/backup/work" -v "$STATE:/backup/state" \
        -e PGHOST="$DB" -e PGPORT=5432 -e PGDATABASE=finance -e PGUSER=finance -e PGPASSWORD="$PGPASS" \
        -e S3_BUCKET="$BUCKET" -e S3_ENDPOINT="$1" -e AWS_REGION=us-east-1 \
        -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
        -e RETENTION_DAYS="${2:-14}" -e RETENTION_MONTHLY=12 -e VERIFY_RESTORES=true \
        "$IMG" --once 2>&1
}

backup_run_db() { # backup_run_db <database> <endpoint> [retention_days]
    docker run --rm --network "$NET" -v "$WORK:/backup/work" -v "$STATE:/backup/state" \
        -e PGHOST="$DB" -e PGPORT=5432 -e PGDATABASE="$1" -e PGUSER=finance -e PGPASSWORD="$PGPASS" \
        -e S3_BUCKET="$BUCKET" -e S3_ENDPOINT="$2" -e AWS_REGION=us-east-1 \
        -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
        -e RETENTION_DAYS="${3:-14}" -e RETENTION_MONTHLY=12 -e VERIFY_RESTORES=true \
        "$IMG" --once 2>&1
}

remote_ls() {
    docker run --rm --network "$NET" -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
        -e AWS_DEFAULT_REGION=us-east-1 --entrypoint sh "$IMG" \
        -c "aws --endpoint-url http://$S3:9090 s3 ls s3://$BUCKET/nirvaah/postgres/ | awk '{print \$4}'" 2>/dev/null
}

status_json() { docker run --rm -v "$STATE:/backup/state" "$IMG" --status 2>/dev/null; }
state_file()  { docker run --rm -v "$STATE:/backup/state" --entrypoint sh "$IMG" -c "cat /backup/state/$1 2>/dev/null" 2>/dev/null; }
work_ls()     { docker run --rm -v "$WORK:/backup/work" --entrypoint sh "$IMG" -c "ls -1 /backup/work" 2>/dev/null; }
vol_sh()      { docker run --rm -v "$1:/v" --entrypoint sh "$IMG" -c "$2" 2>/dev/null; }
restore_run() { # restore_run <file> [extra args...]
    local f="$1"; shift
    docker run --rm --network "$NET" -v "$WORK:/backup/work" -v "$STATE:/backup/state" \
        -e PGHOST="$DB" -e PGDATABASE=finance -e PGUSER=finance -e PGPASSWORD="$PGPASS" \
        -e S3_BUCKET="$BUCKET" -e S3_ENDPOINT="http://$S3:9090" -e AWS_REGION=us-east-1 \
        -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
        --entrypoint /backup/restore.sh "$IMG" --file "$f" "$@" 2>&1
}

# ── 1. successful backup, local + remote verified ───────────────────────────
echo "── 1. successful backup"
out=$(backup_run "http://$S3:9090")
check "backup exits 0" 0 "$?"
contains "restore test covers every table" "restore test passed (3 tables" "$out"
contains "remote read-back verified" "remote verified:" "$out"
status=$(status_json)
contains "status ok" '"status":"ok"' "$status"
contains "remote_verified true" '"remote_verified":true' "$status"
contains "last_success carries the remote key" '"remote":"nirvaah/postgres/' "$(state_file last_success.json)"
vol_sh "$WORK" "[ -f /v/latest.dump ] && [ -f /v/latest.dump.sha256 ]" && ok "local copy has a checksum sidecar" || bad "local copy has a checksum sidecar"
vol_sh "$STATE" "[ -d /v/backup.lock ] && echo present" | grep -q present && bad "the owner releases its own lock" || ok "the owner releases its own lock"
[ -n "$(remote_ls)" ] && ok "remote object exists" || bad "remote object exists"

docker run --rm -v "$STATE:/backup/state" -e INTERVAL_HOURS=4 "$IMG" --health >/dev/null 2>&1
check "--health exits 0 after a verified run" 0 "$?"

# ── 2. verify the offsite copy on demand ────────────────────────────────────
echo "── 2. offsite verification"
docker run --rm --network "$NET" -v "$STATE:/backup/state" -e S3_BUCKET="$BUCKET" \
    -e S3_ENDPOINT="http://$S3:9090" -e AWS_REGION=us-east-1 \
    -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
    "$IMG" --verify-remote >/dev/null 2>&1
check "--verify-remote exits 0" 0 "$?"

# ── 3. restore into a scratch database ──────────────────────────────────────
echo "── 3. restore"
out=$(restore_run latest.dump)
check "restore exits 0" 0 "$?"
contains "checksum verified before restore" "checksum ok" "$out"
contains "row counts printed" "alpha" "$out"

# ── 4. corrupted archive is refused ─────────────────────────────────────────
echo "── 4. corruption detection"
vol_sh "$WORK" "cp /v/latest.dump /v/corrupt.dump && sed 's/latest.dump/corrupt.dump/' /v/latest.dump.sha256 > /v/corrupt.dump.sha256 && printf 'tampered' >> /v/corrupt.dump"
out=$(restore_run corrupt.dump)
check "checksum mismatch refused" 1 "$?"
contains "mismatch is explained" "checksum mismatch" "$out"

vol_sh "$WORK" "head -c 200 /v/latest.dump > /v/broken.dump; rm -f /v/broken.dump.sha256"
out=$(restore_run broken.dump --force)
check "unrestorable archive refused even with --force" 1 "$?"
contains "structure check reported" "not restorable" "$out"

# ── 5. live target needs the explicit flag ──────────────────────────────────
out=$(restore_run latest.dump --into finance)
check "live target refused without --into-live" 1 "$?"
contains "refusal names the flag" "--into-live" "$out"

# ── 6. dead access key (simulated 403, the production failure) ──────────────
echo "── 6. invalid credentials (simulated 403 InvalidAccessKeyId)"
docker exec "$DB" psql -U finance -d finance -q -c "INSERT INTO beta VALUES (2,'c');" >/dev/null
before=$(state_file last_success.json)
out=$(backup_run "http://$DENIED:9000")
check "rejected credentials exit 1" 1 "$?"
contains "failure is logged" "upload failed" "$out"
status=$(status_json)
contains "status upload-failed" '"status":"upload-failed"' "$status"
contains "last_run_ok false" '"last_run_ok":false' "$status"
docker run --rm -v "$STATE:/backup/state" -e INTERVAL_HOURS=4 "$IMG" --health >/dev/null 2>&1
check "--health exits 1 after a failed run" 1 "$?"
check "last_success untouched by a failure" "$before" "$(state_file last_success.json)"
check "lock released after failure" "" "$(vol_sh "$STATE" "ls /backup/state/backup.lock 2>/dev/null; true")"

# ── 7. network failure ──────────────────────────────────────────────────────
echo "── 7. unreachable endpoint"
docker exec "$DB" psql -U finance -d finance -q -c "INSERT INTO beta VALUES (3,'d');" >/dev/null
out=$(backup_run "http://127.0.0.1:9")
check "unreachable endpoint exits 1" 1 "$?"
contains "network failure logged" "upload failed" "$out"

# ── 8. remote content mismatch ──────────────────────────────────────────────
echo "── 8. remote integrity mismatch"
key=$(sed -n 's/.*"remote":"\([^"]*\)".*/\1/p' <<<"$before" 2>/dev/null || true)
docker run --rm --network "$NET" -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
    -e AWS_DEFAULT_REGION=us-east-1 --entrypoint sh "$IMG" \
    -c "printf 'not the backup' > /tmp/x && aws --endpoint-url http://$S3:9090 s3 cp /tmp/x s3://$BUCKET/$key --metadata sha256=deadbeef" >/dev/null 2>&1
docker run --rm --network "$NET" -v "$STATE:/backup/state" -e S3_BUCKET="$BUCKET" \
    -e S3_ENDPOINT="http://$S3:9090" -e AWS_REGION=us-east-1 \
    -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
    "$IMG" --verify-remote >/dev/null 2>&1
check "tampered remote copy fails verification" 1 "$?"

# ── 9. retention after a verified success ───────────────────────────────────
echo "── 9. retention (success)"
vol_sh "$WORK" "cp /v/latest.dump /v/nirvaah-finance-20200115T000000Z.dump && touch -d '2020-01-16' /v/nirvaah-finance-20200115T000000Z.dump"
docker run --rm --network "$NET" -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
    -e AWS_DEFAULT_REGION=us-east-1 --entrypoint sh "$IMG" \
    -c "printf 'old' > /tmp/o && aws --endpoint-url http://$S3:9090 s3 cp /tmp/o s3://$BUCKET/nirvaah/postgres/nirvaah-finance-20200115T000000Z.dump" >/dev/null 2>&1
docker exec "$DB" psql -U finance -d finance -q -c "INSERT INTO alpha VALUES (3,'c');" >/dev/null
out=$(backup_run "http://$S3:9090" 1)
check "retained run exits 0" 0 "$?"
work_ls | grep -q '20200115T000000Z' && bad "old local archive pruned" || ok "old local archive pruned"
remote_ls | grep -q '20200115T000000Z' && bad "old remote archive pruned" || ok "old remote archive pruned"
work_ls | grep -q 'latest.dump' && ok "newest local copy kept" || bad "newest local copy kept"
vol_sh "$WORK" "cp /v/latest.dump /v/nirvaah-finance-20190101T000000Z.dump && touch -d '2019-01-02' /v/nirvaah-finance-20190101T000000Z.dump"
docker exec "$DB" psql -U finance -d finance -q -c "INSERT INTO gamma VALUES (4,'j');" >/dev/null
backup_run "http://$S3:9090" 1 >/dev/null
work_ls | grep -q '20190101T000000Z' && ok "monthly archive kept beyond the retention window" || bad "monthly archive kept beyond the retention window"

# ── 10. retention suspended after a failure ─────────────────────────────────
echo "── 10. retention (failure)"
vol_sh "$WORK" "cp /v/latest.dump /v/nirvaah-finance-20200116T000000Z.dump && touch -d '2020-01-17' /v/nirvaah-finance-20200116T000000Z.dump"
docker exec "$DB" psql -U finance -d finance -q -c "INSERT INTO alpha VALUES (4,'d');" >/dev/null
out=$(backup_run "http://$DENIED:9000" 1)
check "failing run exits 1" 1 "$?"
work_ls | grep -q '20200116T000000Z' && ok "old local archive kept while uploads fail" || bad "old local archive kept while uploads fail"
remote_ls | grep -q 'nirvaah-finance-' && ok "remote archives left untouched on failure" || bad "remote archives left untouched on failure"

# ── 11. concurrency ─────────────────────────────────────────────────────────
echo "── 11. overlapping runs"
# The real Docker shape: the holder is PID 1 inside its own container, so its
# owner file starts with "1". A second invocation is also PID 1 — a PID-only
# ownership check therefore lets its EXIT trap delete the live holder's lock.
ACTIVE_OWNER='1
12345
other-container'
vol_sh "$STATE" "mkdir -p /v/backup.lock && printf '1\n12345\nother-container\n' > /v/backup.lock/owner && date -u +%s > /v/backup.lock/heartbeat"

out=$(backup_run "http://$S3:9090")
check "overlapping run exits 0 (skips cleanly)" 0 "$?"
contains "overlap is announced" "another backup is running" "$out"
owner_now=$(vol_sh "$STATE" "cat /v/backup.lock/owner 2>/dev/null")
check "a skipped run leaves the active lock untouched" "$ACTIVE_OWNER" "$(printf '%s' "$owner_now" | tr -d '\r')"

out=$(backup_run "http://$S3:9090")
check "a third run still cannot acquire the held lock" 0 "$?"
contains "third run also skips" "another backup is running" "$out"

# stale lock: the heartbeat has gone quiet long past the threshold
vol_sh "$STATE" "printf '1\n12345\nother-container\n' > /v/backup.lock/owner && date -u -d \"@$(( $(date -u +%s) - 7200 ))\" +%s > /v/backup.lock/heartbeat"
out=$(backup_run "http://$S3:9090")
check "stale lock is reclaimed" 0 "$?"
contains "stale lock logged" "clearing stale lock" "$out"

# same host, live PID but a different start time: a recycled PID, not the holder
out=$(docker run --rm --network "$NET" -v "$STATE:/backup/state" \
    -e PGHOST="$DB" -e PGPASSWORD="$PGPASS" -e PGUSER=finance -e PGDATABASE=finance \
    -e LOCK_STALE_MINUTES=30 --entrypoint sh "$IMG" -c '
        mkdir -p /backup/state/backup.lock
        printf "%s\n%s\n%s\n" 1 999999 "$(hostname)" > /backup/state/backup.lock/owner
        date -u +%s > /backup/state/backup.lock/heartbeat
        exec /backup/backup.sh --once' 2>&1)
check "recycled PID on the same host runs through" 0 "$?"
contains "recycled PID is treated as stale" "clearing stale lock" "$out"

# ── 12. verification fails closed when nothing is discovered ────────────────
echo "── 12. empty table discovery"
docker exec "$DB" psql -U finance -d postgres -q -c "DROP DATABASE IF EXISTS empty_db;" >/dev/null
docker exec "$DB" psql -U finance -d postgres -q -c "CREATE DATABASE empty_db;" >/dev/null
remote_before=$(remote_ls | grep -c . || true)
# an aged archive retention would delete, if this run were allowed to prune
vol_sh "$WORK" "cp /v/latest.dump /v/nirvaah-finance-20200315T000000Z.dump && touch -d '2020-03-16' /v/nirvaah-finance-20200315T000000Z.dump"
out=$(backup_run_db empty_db "http://$S3:9090" 1)
check "empty discovery fails the run" 1 "$?"
contains "empty discovery is explained" "no tables discovered to verify" "$out"
status=$(status_json)
contains "status is verify-failed" '"status":"verify-failed"' "$status"
contains "the failed run is not marked verified" '"remote_verified":false' "$status"
check "nothing was uploaded" "$remote_before" "$(remote_ls | grep -c . || true)"
work_ls | grep -q '20200315T000000Z' && ok "retention did not run after the failure" || bad "retention did not run after the failure"
check "no verification database left behind" "" \
    "$(docker exec "$DB" psql -U finance -d postgres -t -A -c "SELECT datname FROM pg_database WHERE datname='nirvaah_verify';" | tr -d ' \r')"

# ── 13. the discovery query itself fails ────────────────────────────────────
echo "── 13. table-discovery query failure"
out=$(docker run --rm --network "$NET" -v "$WORK:/backup/work" -v "$STATE:/backup/state" \
    -v "$HERE/psql_fail_discovery.sh:/shim/psql:ro" \
    -e PGHOST="$DB" -e PGPORT=5432 -e PGDATABASE=finance -e PGUSER=finance -e PGPASSWORD="$PGPASS" \
    -e S3_BUCKET="$BUCKET" -e S3_ENDPOINT="http://$S3:9090" -e AWS_REGION=us-east-1 \
    -e AWS_ACCESS_KEY_ID="$S3_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET" \
    --entrypoint sh "$IMG" -c '
        mkdir -p /tmp/shim && cp /shim/psql /tmp/shim/psql && chmod +x /tmp/shim/psql
        PATH=/tmp/shim:$PATH exec /backup/backup.sh --once' 2>&1)
check "failed discovery fails the run" 1 "$?"
contains "failed discovery is explained" "no tables discovered to verify" "$out"
contains "status is verify-failed after discovery failure" '"status":"verify-failed"' "$(status_json)"

# ── 14. cleanup ─────────────────────────────────────────────────────────────
echo "── 14. cleanup"
check "no verification database left behind" "" \
    "$(docker exec "$DB" psql -U finance -d postgres -t -A -c "SELECT datname FROM pg_database WHERE datname='nirvaah_verify';" | tr -d ' \r')"
vol_sh "$STATE" "[ -d /v/backup.lock ] && echo present" | grep -q present && bad "lock removed after the run" || ok "lock removed after the run"
[ "$(vol_sh "$WORK" "ls -1 /v/.tmp 2>/dev/null | wc -l" | tr -d ' ')" = "0" ] && ok "no temp downloads left behind" || bad "no temp downloads left behind"
status=$(status_json)
contains "status retains last_success" '"last_success":{"at"' "$status"

# ── 15. live restore path (last: it replaces the test database) ─────────────
echo "── 15. live restore"
live_before=$(docker exec "$DB" psql -U finance -d finance -t -A -c "SELECT count(*) FROM gamma;" | tr -d ' \r')
out=$(restore_run latest.dump --into-live)
check "live restore exits 0 with --into-live" 0 "$?"
contains "live restore targeted the live database" "restored over the live database" "$out"
check "live data comes back unchanged" "$live_before" \
    "$(docker exec "$DB" psql -U finance -d finance -t -A -c "SELECT count(*) FROM gamma;" | tr -d ' \r')"

echo
echo "── $pass passed, $fail failed"
[ "$fail" = 0 ] || exit 1
