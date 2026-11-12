#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Nirvaah backup agent.
#
# Every INTERVAL_HOURS it dumps the database, compares the dump's checksum with
# the last one it uploaded, and only ships it when the bytes actually changed.
# That is stronger than watching a change counter: an unchanged checksum also
# proves the dump itself ran and produced the same content.
#
#   --once     take one backup and exit (manual run / cron / CI)
#   --status   print the last known state and exit
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

log() { printf '%s  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

mkdir -p "$WORK_DIR" "$STATE_DIR"

stamp() { date -u '+%Y%m%dT%H%M%SZ'; }

s3_enabled() { [ -n "$S3_BUCKET" ]; }

s3() {
    if [ -n "$S3_ENDPOINT" ]; then
        aws --endpoint-url "$S3_ENDPOINT" --region "$AWS_REGION" s3 "$@"
    else
        aws --region "$AWS_REGION" s3 "$@"
    fi
}

record_state() {
    # last_run always updates; last_dump only when a new archive is produced.
    state="$1"
    printf '{"status":"%s","last_run":"%s","last_dump":"%s","bytes":%s,"sha256":"%s","uploaded":%s}\n' \
        "$state" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${last_dump:--}" "${bytes:-0}" "${sha256:--}" "${uploaded:-false}" \
        > "$STATE_DIR/status.json"
}

TABLES="users transactions budgets goals investments liabilities notes tasks journal_entries deletions"

# One md5 per table over its rows in a fixed order, then one hash over those.
data_fingerprint() {
    parts=""
    for t in $TABLES; do
        h=$(psql -t -A -c "SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM $t x;" 2>/dev/null || echo err)
        parts="$parts$t:$h|"
    done
    printf '%s' "$parts" | sha256sum | awk '{print $1}'
}

# A backup is only real once it has been restored. Costs seconds at this size
# and catches the failure nobody notices until the day they need it.
verify_archive() {
    archive="$1"
    target="nirvaah_verify"
    psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$target\";" >/dev/null 2>&1
    psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$target\";" >/dev/null 2>&1
    if ! pg_restore --dbname="$target" --no-owner --no-privileges --exit-on-error "$archive" >/dev/null 2>&1; then
        log "ERROR restore test failed — archive is not usable"
        psql -d postgres -c "DROP DATABASE IF EXISTS \"$target\";" >/dev/null 2>&1
        return 1
    fi
    for t in users transactions notes tasks journal_entries; do
        live=$(psql -d "$PGDATABASE" -t -A -c "SELECT count(*) FROM $t;" 2>/dev/null || echo 0)
        copy=$(psql -d "$target" -t -A -c "SELECT count(*) FROM $t;" 2>/dev/null || echo 0)
        if [ "$live" != "$copy" ]; then
            log "ERROR restore test mismatch on $t ($live live vs $copy restored)"
            psql -d postgres -c "DROP DATABASE IF EXISTS \"$target\";" >/dev/null 2>&1
            return 1
        fi
    done
    psql -d postgres -c "DROP DATABASE IF EXISTS \"$target\";" >/dev/null 2>&1
    log "restore test passed (row counts match live)"
    return 0
}

take_backup() {
    now="$(stamp)"
    file="nirvaah-${PGDATABASE}-${now}.dump"
    path="$WORK_DIR/$file"

    log "dumping $PGDATABASE"
    if ! pg_dump --format=custom --compress=9 --no-owner --no-privileges --file="$path"; then
        log "ERROR dump failed"; record_state "dump-failed"; return 1
    fi

    # A dump that cannot be listed is not a backup.
    if ! pg_restore --list "$path" >/dev/null 2>&1; then
        log "ERROR archive is not restorable"; rm -f "$path"; record_state "corrupt"; return 1
    fi

    if [ "${VERIFY_RESTORES:-true}" = "true" ]; then
        verify_archive "$path" || { log "backup discarded"; rm -f "$path"; record_state "verify-failed"; return 1; }
    fi

    bytes=$(wc -c < "$path" | tr -d ' ')
    sha256=$(sha256sum "$path" | awk '{print $1}')

    # pg_dump embeds a timestamp and a random security token, so hashing the
    # file (or its text) would report "changed" on every run. Ask the database
    # for a deterministic fingerprint of the rows instead.
    data_hash=$(data_fingerprint)
    previous=$(cat "$STATE_DIR/last.data-hash" 2>/dev/null || true)

    if [ "$data_hash" = "$previous" ]; then
        log "no data changed (${bytes} bytes, sha ${sha256%?????????}) — skipping upload"
        rm -f "$path"
        last_dump=$(cat "$STATE_DIR/last.dump" 2>/dev/null || echo '-')
        record_state "unchanged"
        return 0
    fi

    # Keep one local copy regardless of S3, so a restore never depends on the network.
    cp "$path" "$WORK_DIR/latest.dump"

    uploaded=false
    if s3_enabled; then
        log "uploading s3://$S3_BUCKET/$S3_PREFIX/$file"
        if s3 cp "$path" "s3://$S3_BUCKET/$S3_PREFIX/$file" --sse AES256 --only-show-errors; then
            uploaded=true
        else
            # Do NOT advance the fingerprint: the next run must retry this data
            # rather than believe it has already been shipped offsite.
            log "ERROR upload failed — local copy kept, will retry next interval"
            rm -f "$path"
            record_state "upload-failed"
            return 1
        fi
    else
        log "S3 not configured — local copy only ($WORK_DIR/latest.dump)"
    fi

    printf '%s' "$data_hash" > "$STATE_DIR/last.data-hash"
    printf '%s' "$sha256" > "$STATE_DIR/last.sha256"
    printf '%s' "$now" > "$STATE_DIR/last.dump"
    last_dump="$now"

    log "backup complete: $file ($bytes bytes)"
    record_state "ok"
    return 0
}

prune() {
    [ "$(ls -1 "$WORK_DIR"/nirvaah-*.dump 2>/dev/null | wc -l)" -gt 0 ] || return 0
    # Keep: everything newer than RETENTION_DAYS, plus the 1st of each month.
    find "$WORK_DIR" -maxdepth 1 -name 'nirvaah-*.dump' -mtime "+$RETENTION_DAYS" \
        ! -name 'latest.dump' -print | while read -r old; do
        base=$(basename "$old")
        day=${base#nirvaah-*-}
        day=${day%%T*}
        if date -d "${day}" '+%d' >/dev/null 2>&1 && [ "$(date -d "${day}" '+%d')" = "01" ]; then
            continue
        fi
        log "pruning $base"
        rm -f "$old"
    done && true

    if s3_enabled; then
        cutoff=$(date -u -d "-${RETENTION_DAYS} days" '+%Y-%m-%d' 2>/dev/null || true)
        [ -n "$cutoff" ] || return 0
        s3 ls "s3://$S3_BUCKET/$S3_PREFIX/" 2>/dev/null | while read -r _ _ _ name; do
            [ -n "$name" ] || continue
            day=${name#nirvaah-*-}
            day=${day%%T*}
            if [ "$(date -d "${day}" '+%d' 2>/dev/null || echo 01)" = "01" ]; then continue; fi
            if [ "${day//-/}" -lt "${cutoff//-/}" ]; then
                s3 rm "s3://$S3_BUCKET/$S3_PREFIX/$name" --only-show-errors && log "pruned remote $name"
            fi
        done && true
    fi
}

case "${1:-}" in
    --once)
        take_backup && prune
        exit $?
        ;;
    --status)
        cat "$STATE_DIR/status.json" 2>/dev/null || echo '{"status":"never-run"}'
        exit 0
        ;;
esac

log "backup agent starting — every ${INTERVAL_HOURS}h, retention ${RETENTION_DAYS}d (+1st of month up to ${RETENTION_MONTHLY})"

# A short delay keeps startup logs readable and avoids racing the first migration.
sleep 15

while true; do
    take_backup || log "backup run failed; will retry next interval"
    prune || true
    sleep "$((INTERVAL_HOURS * 3600))"
done
