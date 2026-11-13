#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Nirvaah backup agent.
#
# Every INTERVAL_HOURS it dumps the database, restores the archive into a scratch
# database, fingerprints the rows to decide whether anything changed, uploads to
# S3 and then *reads the object back* to prove it arrived intact.
#
#   --once           take one backup and exit (manual run / cron / CI)
#   --status         print the last known state as JSON and exit
#   --verify-remote  re-download the newest offsite copy and check its checksum
#
# Failure policy, in one paragraph: a run only counts as a success once the
# archive has been restored locally *and* the remote object has been read back and
# matched byte for byte. status.json always describes the latest run, while
# last_success.json is written only by a fully verified run and is never cleared
# by a failure. Retention runs only after a verified success, and it never removes
# the newest verified local copy or the newest verified remote object — so a
# credential outage leaves every offsite archive in place until backups work again.
# ─────────────────────────────────────────────────────────────────────────────
set -eu

INTERVAL_HOURS="${INTERVAL_HOURS:-4}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
RETENTION_MONTHLY="${RETENTION_MONTHLY:-12}"
WORK_DIR=/backup/work
STATE_DIR=/backup/state
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-nirvaah/postgres}"
S3_ENDPOINT="${S3_ENDPOINT:-}"
AWS_REGION="${AWS_REGION:-ap-south-1}"

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:-finance}"
PGUSER="${PGUSER:-finance}"
export PGHOST PGPORT PGDATABASE PGUSER
export PGPASSWORD="${PGPASSWORD:-}"

VERIFY_DB="nirvaah_verify"
LOCK_DIR="$STATE_DIR/backup.lock"
STATUS_FILE="$STATE_DIR/status.json"
SUCCESS_FILE="$STATE_DIR/last_success.json"
TMP_DIR="$WORK_DIR/.tmp"

log() { printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

mkdir -p "$WORK_DIR" "$STATE_DIR" "$TMP_DIR"

stamp() { date -u '+%Y%m%dT%H%M%SZ'; }
iso_now() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
s3_enabled() { [ -n "$S3_BUCKET" ]; }

s3() {
    if [ -n "$S3_ENDPOINT" ]; then
        aws --endpoint-url "$S3_ENDPOINT" --region "$AWS_REGION" s3 "$@"
    else
        aws --region "$AWS_REGION" s3 "$@"
    fi
}

s3api() {
    if [ -n "$S3_ENDPOINT" ]; then
        aws --endpoint-url "$S3_ENDPOINT" --region "$AWS_REGION" s3api "$@"
    else
        aws --region "$AWS_REGION" s3api "$@"
    fi
}

# ── lock ────────────────────────────────────────────────────────────────────
# Atomic directory creation (busybox has no flock). The owner file records the PID,
# the process start time from /proc and the hostname. Same host → the PID and start
# time are authoritative, so a recycled PID is not mistaken for the holder. Another
# container on the same volume has its own PID namespace, so there the heartbeat is
# the signal: the holder refreshes it while it runs, and the lock is only considered
# abandoned once that heartbeat has gone quiet for LOCK_STALE_MINUTES.

HOST_NAME=$(hostname 2>/dev/null || echo unknown)
STALE_MINUTES="${LOCK_STALE_MINUTES:-30}"
heartbeat_pid=""

proc_start() { if [ -r "/proc/$1/stat" ]; then awk '{print $22}' "/proc/$1/stat" 2>/dev/null; else echo "-"; fi; }

# The identity of a lock owner: PID, the process start time from /proc, hostname.
# Every container runs this script as PID 1, so a bare PID identifies "some
# container's init" rather than the owner — release and reclaim must compare all
# three, or a second container's EXIT trap deletes a live holder's lock.
my_owner() { printf '%s\n%s\n%s\n' "$$" "$(proc_start $$)" "$HOST_NAME"; }

start_heartbeat() {
    ( while :; do date -u +%s > "$LOCK_DIR/heartbeat" 2>/dev/null || exit 0; sleep 30; done ) &
    heartbeat_pid=$!
}

stop_heartbeat() {
    if [ -n "${heartbeat_pid:-}" ]; then kill "$heartbeat_pid" 2>/dev/null || true; fi
    heartbeat_pid=""
}

lock_held_by_live_process() {
    owner_pid=$(sed -n '1p' "$LOCK_DIR/owner" 2>/dev/null || echo "")
    owner_start=$(sed -n '2p' "$LOCK_DIR/owner" 2>/dev/null || echo "")
    owner_host=$(sed -n '3p' "$LOCK_DIR/owner" 2>/dev/null || echo "")
    [ -n "$owner_pid" ] || return 1

    if [ "$owner_host" = "$HOST_NAME" ]; then
        kill -0 "$owner_pid" 2>/dev/null || return 1              # process gone → stale
        [ "$(proc_start "$owner_pid")" = "$owner_start" ]          # PID reused? → stale
        return $?
    fi

    # Different container: verify liveness through the heartbeat, not the PID.
    beat=$(cat "$LOCK_DIR/heartbeat" 2>/dev/null || echo 0)
    now=$(date -u +%s)
    case "$beat" in ''|*[!0-9]*) beat=0 ;; esac
    [ $((now - beat)) -lt $((STALE_MINUTES * 60)) ]
}

acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        if ! my_owner > "$LOCK_DIR/owner" 2>/dev/null; then
            log "lock vanished while acquiring — skipping this cycle"
            return 1
        fi
        start_heartbeat
        return 0
    fi
    if lock_held_by_live_process; then
        log "another backup is running (pid $owner_pid on ${owner_host:-?}) — skipping this cycle"
        return 1
    fi

    # No live holder. Remember the exact owner we judged stale, and refuse to
    # delete anything else: another run may have reclaimed or re-created the lock
    # between the liveness check and the removal.
    stale_owner=$(cat "$LOCK_DIR/owner" 2>/dev/null || echo "")
    if [ -z "$stale_owner" ]; then
        # An owner file that was never written (killed mid-acquire) is only
        # cleared once it is clearly abandoned, so we do not race a starting run.
        if find "$LOCK_DIR" -maxdepth 0 -mmin +2 | grep -q .; then
            log "clearing abandoned lock (no owner file, older than 2m)"
        else
            log "another backup is starting — skipping this cycle"
            return 1
        fi
    fi
    if [ "$(cat "$LOCK_DIR/owner" 2>/dev/null || echo "")" != "$stale_owner" ]; then
        log "lock changed while being reclaimed — skipping this cycle"
        return 1
    fi
    if [ -n "$stale_owner" ]; then
        log "clearing stale lock from pid ${owner_pid:-?} on ${owner_host:-?} (no live holder)"
    fi
    rm -rf "$LOCK_DIR"

    mkdir "$LOCK_DIR" 2>/dev/null || { log "could not take the lock — skipping"; return 1; }
    if ! my_owner > "$LOCK_DIR/owner" 2>/dev/null; then
        log "lost the lock while acquiring — skipping this cycle"
        return 1
    fi
    start_heartbeat
    return 0
}

release_lock() {
    stop_heartbeat
    [ -d "$LOCK_DIR" ] || return 0
    # Full identity, not just the PID: a run that never owned the lock (every
    # container is PID 1) must not delete the holder's lock from its EXIT trap.
    if [ "$(cat "$LOCK_DIR/owner" 2>/dev/null || echo "")" = "$(my_owner)" ]; then
        rm -rf "$LOCK_DIR"
    fi
    return 0
}

trap 'release_lock' EXIT
trap 'release_lock; exit 130' INT TERM HUP

# ── state ───────────────────────────────────────────────────────────────────
# status.json = the latest run (this is what health reads).
# last_success.json = the newest fully verified backup (local and, when configured,
# remote). A failure never touches it, so "what is my newest recoverable backup?"
# always has an answer.

last_success_json() { cat "$SUCCESS_FILE" 2>/dev/null || printf 'null'; }

record_state() {
    state="$1"
    ok=false
    [ "$state" = "ok" ] && ok=true
    [ "$state" = "unchanged" ] && ok=true
    printf '{"status":"%s","last_run":"%s","last_run_epoch":%s,"last_run_ok":%s,"last_dump":"%s","bytes":%s,"sha256":"%s","uploaded":%s,"remote_verified":%s,"last_success":%s}\n' \
        "$state" "$(iso_now)" "$(date -u +%s)" "$ok" \
        "${last_dump:--}" "${bytes:-0}" "${sha256:--}" \
        "${uploaded:-false}" "${remote_verified:-false}" \
        "$(last_success_json)" \
        > "$STATUS_FILE.tmp"
    mv "$STATUS_FILE.tmp" "$STATUS_FILE"
}

write_success() {
    printf '{"at":"%s","file":"%s","bytes":%s,"sha256":"%s","remote":"%s","remote_verified":%s,"remote_verified_at":"%s"}\n' \
        "$(iso_now)" "$1" "$2" "$3" "${4:-}" "${5:-false}" "${6:-}" \
        > "$SUCCESS_FILE.tmp"
    mv "$SUCCESS_FILE.tmp" "$SUCCESS_FILE"
}

# ── local integrity ─────────────────────────────────────────────────────────
# Every archive gets a sidecar so a restore can prove the bytes it is about to
# load are the bytes that were written.

sha_of() { sha256sum "$1" | awk '{print $1}'; }

write_sidecar() {
    # Same convention as sha256sum: "<hash>  <basename>"
    ( cd "$(dirname "$1")" && printf '%s  %s\n' "$(sha_of "$1")" "$(basename "$1")" > "$(basename "$1").sha256" )
}

verify_sidecar() {
    path="$1"
    sidecar="$path.sha256"
    [ -f "$sidecar" ] || { log "WARN no checksum sidecar for $(basename "$path")"; return 2; }
    if ( cd "$(dirname "$path")" && sha256sum -c "$(basename "$sidecar")" >/dev/null 2>&1 ); then
        return 0
    fi
    log "CHECKSUM MISMATCH for $(basename "$path")"
    return 1
}

# ── database helpers ────────────────────────────────────────────────────────
# Derived from the catalogue, not a hardcoded list: a new table is covered the day
# it ships rather than the day someone remembers to add it.

public_tables() {
    psql -t -A -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;" | tr -d '\r'
}

data_fingerprint() {
    parts=""
    for t in $(public_tables); do
        h=$(psql -t -A -c "SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM \"$t\" x;" 2>/dev/null || echo err)
        parts="$parts$t:$h|"
    done
    printf '%s' "$parts" | sha256sum | awk '{print $1}'
}

# A backup is only real once it has been restored. The target is a scratch database
# and is asserted not to be the live one — verification must never touch prod.
verify_archive() {
    archive="$1"
    if [ "$VERIFY_DB" = "$PGDATABASE" ]; then
        log "ERROR refusing to verify into the live database ($VERIFY_DB)"
        return 1
    fi
    psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$VERIFY_DB\";" >/dev/null 2>&1
    if ! psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$VERIFY_DB\";" >/dev/null 2>&1; then
        log "ERROR could not create $VERIFY_DB (needs CREATEDB)"
        return 1
    fi
    if ! pg_restore --dbname="$VERIFY_DB" --no-owner --no-privileges --exit-on-error "$archive" >/dev/null 2>&1; then
        log "ERROR restore test failed — archive is not usable"
        psql -d postgres -c "DROP DATABASE IF EXISTS \"$VERIFY_DB\";" >/dev/null 2>&1
        return 1
    fi
    mismatch=0
    checked=0
    for t in $(public_tables); do
        checked=$((checked + 1))
        live=$(psql -d "$PGDATABASE" -t -A -c "SELECT count(*) FROM \"$t\";" 2>/dev/null || echo 0)
        copy=$(psql -d "$VERIFY_DB" -t -A -c "SELECT count(*) FROM \"$t\";" 2>/dev/null || echo 0)
        if [ "$live" != "$copy" ]; then
            log "ERROR restore test mismatch on $t ($live live vs $copy restored)"
            mismatch=1
            break
        fi
        # Row counts alone would pass a restore that lost a column's values, so
        # compare a content digest per table as well.
        live_h=$(psql -d "$PGDATABASE" -t -A -c "SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM \"$t\" x;" 2>/dev/null || echo err)
        copy_h=$(psql -d "$VERIFY_DB" -t -A -c "SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM \"$t\" x;" 2>/dev/null || echo err)
        if [ "$live_h" = "err" ] || [ "$copy_h" = "err" ]; then
            log "WARN could not digest $t; row count only"
        elif [ "$live_h" != "$copy_h" ]; then
            log "ERROR restore test content mismatch on $t"
            mismatch=1
            break
        fi
    done
    psql -d postgres -c "DROP DATABASE IF EXISTS \"$VERIFY_DB\";" >/dev/null 2>&1
    [ "$mismatch" = 0 ] || return 1
    # An empty catalogue means nothing was actually verified — a failed discovery
    # query or a database with no public tables. Passing here would let an
    # unverified archive be uploaded and retained.
    if [ "$checked" -le 0 ]; then
        log "ERROR no tables discovered to verify — refusing the backup"
        return 1
    fi
    log "restore test passed ($checked tables, row counts match live)"
    return 0
}

# ── remote integrity ────────────────────────────────────────────────────────
# The CLI's exit code only says the request was accepted. Read the object back:
# size from head-object must equal the local file, the sha256 we recorded at upload
# time must come back as object metadata, and the downloaded bytes must hash to the
# same value. ETag is deliberately not used as a content checksum (multipart ETags
# are not an md5 of the object, and on SSE-KMS they are not an md5 at all).

remote_get_sha() {   # $1 = key; prints the sha256 stored as object metadata
    s3api head-object --bucket "$S3_BUCKET" --key "$1" \
        --query 'Metadata.sha256' --output text 2>/dev/null | tr -d '\r'
}

remote_get_size() {
    s3api head-object --bucket "$S3_BUCKET" --key "$1" \
        --query 'ContentLength' --output text 2>/dev/null | tr -d '\r'
}

verify_remote() {    # $1 = key, $2 = local path (unused), $3 = expected sha256, $4 = bytes
    key="$1"; expect="$3"; expect_bytes="$4"
    if [ "$(remote_get_size "$key")" != "$expect_bytes" ]; then
        log "ERROR remote size mismatch for $key (expected $expect_bytes)"
        return 1
    fi
    if [ "$(remote_get_sha "$key")" != "$expect" ]; then
        log "ERROR remote metadata sha256 mismatch for $key"
        return 1
    fi
    dl="$TMP_DIR/verify-$$.dump"
    rm -f "$dl"
    if ! s3 cp "s3://$S3_BUCKET/$key" "$dl" --only-show-errors >/dev/null 2>&1; then
        log "ERROR could not download $key for verification"
        rm -f "$dl"
        return 1
    fi
    actual=$(sha_of "$dl")
    rm -f "$dl"
    if [ "$actual" != "$expect" ]; then
        log "ERROR remote content mismatch for $key ($actual != $expect)"
        return 1
    fi
    log "remote verified: $key ($expect_bytes bytes, sha ${expect%?????????})"
    return 0
}

# ── retention ───────────────────────────────────────────────────────────────
# Runs only after a fully verified success, and always spares the newest verified
# local copy, its sidecar, and the newest verified remote object.

last_success_file()  { sed -n 's/.*"file":"\([^"]*\)".*/\1/p' "$SUCCESS_FILE" 2>/dev/null || true; }
last_success_remote() { sed -n 's/.*"remote":"\([^"]*\)".*/\1/p' "$SUCCESS_FILE" 2>/dev/null || true; }

prune_local() {
    keep=$(last_success_file)
    find "$WORK_DIR" -maxdepth 1 -name 'nirvaah-*.dump' -mtime "+$RETENTION_DAYS" -print | sort |
    while read -r old; do
        base=$(basename "$old")
        [ -n "$keep" ] && [ "$base" = "$keep" ] && { log "keeping newest verified local archive $base"; continue; }
        day=${base#nirvaah-*-}
        day=${day%%T*}
        if [ "${day#??????}" = "01" ]; then
            continue      # monthly archives are capped below, not by age
        fi
        log "pruning local $base"
        rm -f "$old" "$old.sha256"
    done

    # Monthly set: keep only the newest RETENTION_MONTHLY first-of-month archives.
    find "$WORK_DIR" -maxdepth 1 -name 'nirvaah-*-01T*.dump' -print | sort -r |
    tail -n "+$((RETENTION_MONTHLY + 1))" |
    while read -r old; do
        base=$(basename "$old")
        [ -n "$keep" ] && [ "$base" = "$keep" ] && continue
        log "pruning local monthly $base (beyond ${RETENTION_MONTHLY})"
        rm -f "$old" "$old.sha256"
    done
}

prune_remote() {
    s3_enabled || return 0
    keep=$(last_success_remote)
    cutoff_epoch=$(( $(date -u +%s) - RETENTION_DAYS * 86400 ))
    cutoff=$(date -u -d "@${cutoff_epoch}" '+%Y-%m-%d' 2>/dev/null || true)
    [ -n "$cutoff" ] || { log "WARN cannot compute the retention cutoff — remote prune skipped"; return 0; }
    names=$(s3 ls "s3://$S3_BUCKET/$S3_PREFIX/" 2>/dev/null | awk '{print $4}' | tr -d '\r' | grep '\.dump$' || true)
    [ -n "$names" ] || return 0

    printf '%s\n' "$names" | grep -v -- '-01T' | sort > "$TMP_DIR/remote-aged.$$"
    printf '%s\n' "$names" | grep -- '-01T' | sort -r | tail -n "+$((RETENTION_MONTHLY + 1))" \
        > "$TMP_DIR/remote-monthly.$$"

    cat "$TMP_DIR/remote-aged.$$" "$TMP_DIR/remote-monthly.$$" | sort -u |
    while read -r name; do
        [ -n "$name" ] || continue
        [ -n "$keep" ] && [ "$name" = "$(basename "$keep")" ] && { log "keeping newest verified remote $(basename "$name")"; continue; }
        day=${name#nirvaah-*-}
        day=${day%%T*}
        case "$name" in
            *-01T*) log "pruning remote monthly $name (beyond ${RETENTION_MONTHLY})" ;;
            *)
                [ "${day//-/}" -lt "${cutoff//-/}" ] || continue
                log "pruning remote $name"
                ;;
        esac
        s3 rm "s3://$S3_BUCKET/$S3_PREFIX/$name" --only-show-errors >/dev/null 2>&1 \
            || log "WARN could not prune $name"
    done
    rm -f "$TMP_DIR/remote-aged.$$" "$TMP_DIR/remote-monthly.$$"
    log "retention applied (keep ${RETENTION_DAYS}d, ${RETENTION_MONTHLY} monthly)"
}

# ── one backup ──────────────────────────────────────────────────────────────
RUN_OUTCOME="failed"

take_backup() {
    now="$(stamp)"
    file="nirvaah-${PGDATABASE}-${now}.dump"
    path="$WORK_DIR/$file"
    uploaded=false
    remote_verified=false

    log "dumping $PGDATABASE"
    if ! pg_dump --format=custom --compress=9 --no-owner --no-privileges --file="$path"; then
        log "ERROR dump failed"; rm -f "$path"; record_state "dump-failed"; return 1
    fi

    if ! pg_restore --list "$path" >/dev/null 2>&1; then
        log "ERROR archive is not restorable"; rm -f "$path"; record_state "corrupt"; return 1
    fi

    if [ "${VERIFY_RESTORES:-true}" = "true" ]; then
        if ! verify_archive "$path"; then
            log "backup discarded"; rm -f "$path"; record_state "verify-failed"; return 1
        fi
    fi

    bytes=$(wc -c < "$path" | tr -d ' ')
    sha256=$(sha_of "$path")
    write_sidecar "$path"

    data_hash=$(data_fingerprint)
    previous=$(cat "$STATE_DIR/last.data-hash" 2>/dev/null || true)

    if [ "$data_hash" = "$previous" ]; then
        log "no data changed (${bytes} bytes, sha ${sha256%?????????}) — skipping upload"
        rm -f "$path" "$path.sha256"
        last_dump=$(last_success_file)
        RUN_OUTCOME="unchanged"
        record_state "unchanged"
        return 0
    fi

    # Local recovery copy first: a restore must never depend on the network.
    cp "$path" "$WORK_DIR/latest.dump"
    write_sidecar "$WORK_DIR/latest.dump"

    if s3_enabled; then
        key="$S3_PREFIX/$file"
        log "uploading s3://$S3_BUCKET/$key"
        if ! s3 cp "$path" "s3://$S3_BUCKET/$key" --sse AES256 \
                --metadata "sha256=$sha256" --only-show-errors; then
            # Keep the local copy and every existing remote archive; do not advance
            # the fingerprint, so the next run retries this data.
            log "ERROR upload failed — local copy kept, retention suspended"
            rm -f "$path" "$path.sha256"
            record_state "upload-failed"
            return 1
        fi
        uploaded=true
        if ! verify_remote "$key" "$path" "$sha256" "$bytes"; then
            log "ERROR upload did not verify — retention suspended, will retry"
            rm -f "$path" "$path.sha256"
            record_state "remote-unverified"
            return 1
        fi
        remote_verified=true
    else
        log "S3 not configured — local copy only ($WORK_DIR/latest.dump)"
    fi

    printf '%s' "$data_hash" > "$STATE_DIR/last.data-hash"
    printf '%s' "$sha256" > "$STATE_DIR/last.sha256"
    printf '%s' "$now" > "$STATE_DIR/last.dump"
    last_dump="$now"

    remote_key=""
    remote_at=""
    if [ "$remote_verified" = true ]; then
        remote_key="$S3_PREFIX/$file"
        remote_at="$(iso_now)"
    fi
    write_success "$file" "$bytes" "$sha256" "$remote_key" "$remote_verified" "$remote_at"

    log "backup complete: $file ($bytes bytes)"
    RUN_OUTCOME="ok"
    record_state "ok"
    return 0
}

# ── entrypoints ─────────────────────────────────────────────────────────────
status_cmd() {
    cat "$STATUS_FILE" 2>/dev/null || printf '{"status":"never-run","last_success":%s}\n' "$(last_success_json)"
}

health_cmd() {
    state=$(sed -n 's/.*"status":"\([^"]*\)".*/\1/p' "$STATUS_FILE" 2>/dev/null || echo never-run)
    epoch=$(sed -n 's/.*"last_run_epoch":\([0-9]*\).*/\1/p' "$STATUS_FILE" 2>/dev/null || echo 0)
    case "$state" in
        ok|unchanged) ;;
        *) log "unhealthy: last run status is $state"; exit 1 ;;
    esac
    case "$epoch" in ''|*[!0-9]*) epoch=0 ;; esac
    [ "$epoch" -gt 0 ] || { log "unhealthy: no completed run recorded"; exit 1; }
    age=$(( $(date -u +%s) - epoch ))
    limit=$(( INTERVAL_HOURS * 7200 ))
    if [ "$age" -gt "$limit" ]; then
        log "unhealthy: last completed run was ${age}s ago, limit ${limit}s"
        exit 1
    fi
    log "healthy: $state, last completed run ${age}s ago"
    exit 0
}

verify_remote_cmd() {
    s3_enabled || { log "S3 is not configured — nothing to verify remotely"; exit 2; }
    key=$(last_success_remote)
    [ -n "$key" ] || { log "no verified remote backup recorded yet"; exit 1; }
    sha=$(sed -n 's/.*"sha256":"\([^"]*\)".*/\1/p' "$SUCCESS_FILE" 2>/dev/null || true)
    bytes=$(sed -n 's/.*"bytes":\([0-9]*\).*/\1/p' "$SUCCESS_FILE" 2>/dev/null || echo 0)
    log "verifying s3://$S3_BUCKET/$key against last_success.json"
    if verify_remote "$key" "" "$sha" "$bytes"; then
        log "offsite copy is intact"
        exit 0
    fi
    log "ERROR offsite copy does not match last_success.json"
    exit 1
}

case "${1:-}" in
    --once)
        acquire_lock || exit 0        # someone else is running; not an error
        if take_backup; then
            if [ "$RUN_OUTCOME" = "ok" ]; then prune_local; prune_remote; fi
            exit 0
        fi
        log "retention suspended until a verified backup succeeds"
        exit 1
        ;;
    --status)
        status_cmd
        exit 0
        ;;
    --health)
        health_cmd
        ;;
    --verify-remote)
        verify_remote_cmd
        ;;
esac

log "backup agent starting — every ${INTERVAL_HOURS}h, retention ${RETENTION_DAYS}d (+${RETENTION_MONTHLY} monthly)"

# A short delay keeps startup logs readable and avoids racing the first migration.
sleep 15

while true; do
    if acquire_lock; then
        if take_backup; then
            if [ "$RUN_OUTCOME" = "ok" ]; then
                prune_local
                prune_remote
            fi
        else
            log "retention suspended until a verified backup succeeds"
        fi
        release_lock
    fi
    sleep "$((INTERVAL_HOURS * 3600))"
done
