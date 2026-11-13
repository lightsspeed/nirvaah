#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Nirvaah restore.
#
#   ./restore.sh --list                          local + remote archives
#   ./restore.sh --file latest.dump              restore into a scratch DB and report
#   ./restore.sh --file latest.dump --into-live  restore over the live database
#
# Safety rules, in order of application:
#   * the archive's checksum is verified before pg_restore runs; a mismatch (or a
#     missing checksum) refuses by default. --force overrides this and nothing else.
#   * restoring over the live database requires --into-live. --force never grants
#     that, and the scratch target can never be the live database name.
# ─────────────────────────────────────────────────────────────────────────────
set -eu

WORK_DIR=/backup/work
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-nirvaah/postgres}"
S3_ENDPOINT="${S3_ENDPOINT:-}"
AWS_REGION="${AWS_REGION:-ap-south-1}"

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-finance}"
export PGHOST PGPORT PGUSER
export PGPASSWORD="${PGPASSWORD:-}"
LIVE_DB="${PGDATABASE:-finance}"

log() { printf '%s  %s\n' "$(date -u '+%H:%M:%SZ')" "$*"; }

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

sha_of() { sha256sum "$1" | awk '{print $1}'; }

file=""
into="nirvaah_restore_check"
force=false
into_live=false

while [ $# -gt 0 ]; do
    case "$1" in
        --list)
            log "local archives in $WORK_DIR:"
            ls -1sh "$WORK_DIR"/nirvaah-*.dump 2>/dev/null || log "  (none)"
            if [ -n "$S3_BUCKET" ]; then
                log "remote archives in s3://$S3_BUCKET/$S3_PREFIX/:"
                s3 ls "s3://$S3_BUCKET/$S3_PREFIX/" 2>/dev/null || log "  (none / no credentials)"
            fi
            exit 0
            ;;
        --file) file="$2"; shift 2 ;;
        --into) into="$2"; shift 2 ;;
        --into-live) into="$LIVE_DB"; into_live=true; shift ;;
        --force) force=true; shift ;;
        *) log "unknown argument: $1"; exit 2 ;;
    esac
done

[ -n "$file" ] || { log "usage: restore.sh --file <archive> [--into <db>|--into-live] [--force]"; exit 2; }

path="$WORK_DIR/$file"
fetched=false
if [ ! -f "$path" ] && [ -n "$S3_BUCKET" ]; then
    log "fetching $file from S3"
    s3 cp "s3://$S3_BUCKET/$S3_PREFIX/$file" "$path" --only-show-errors || { log "not found locally or remotely"; exit 1; }
    fetched=true
fi
[ -f "$path" ] || { log "archive not found: $path"; exit 1; }

# ── checksum, before anything is loaded ─────────────────────────────────────
log "verifying archive checksum"
expected=""
if [ -f "$path.sha256" ]; then
    expected=$(awk 'NR==1 {print $1}' "$path.sha256")
elif [ "$fetched" = true ] && [ -n "$S3_BUCKET" ]; then
    expected=$(s3api head-object --bucket "$S3_BUCKET" --key "$S3_PREFIX/$file" \
                   --query 'Metadata.sha256' --output text 2>/dev/null | tr -d '\r' || true)
fi

if [ -z "$expected" ] || [ "$expected" = "None" ]; then
    if [ "$force" != true ]; then
        log "refusing: no checksum available for $(basename "$path") (pass --force to override)"
        exit 1
    fi
    log "WARNING no checksum available — continuing because --force was given"
else
    actual=$(sha_of "$path")
    if [ "$actual" != "$expected" ]; then
        if [ "$force" != true ]; then
            log "refusing: checksum mismatch (expected ${expected%?????????}, got ${actual%?????????}) — pass --force to override"
            exit 1
        fi
        log "WARNING checksum mismatch accepted because --force was given"
    else
        log "checksum ok (${actual%?????????})"
    fi
fi

log "verifying archive structure"
pg_restore --list "$path" >/dev/null || { log "archive is not restorable"; exit 1; }

# ── target safety ───────────────────────────────────────────────────────────
if [ "$into" = "$LIVE_DB" ] && [ "$into_live" != true ]; then
    log "refusing to overwrite the live database $LIVE_DB without --into-live"
    exit 1
fi
if [ "$into" = "postgres" ] || [ "$into" = "template1" ] || [ "$into" = "template0" ]; then
    log "refusing to restore into the system database $into"
    exit 1
fi

log "creating database $into"
psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$into\";" >/dev/null
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$into\";" >/dev/null

log "restoring into $into"
pg_restore --dbname="$into" --no-owner --no-privileges --exit-on-error "$path"

log "row counts in $into:"
for t in $(psql -d "$into" -t -A -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"); do
    count=$(psql -d "$into" -t -A -c "SELECT count(*) FROM \"$t\";" 2>/dev/null || echo 'n/a')
    printf '  %-20s %s\n' "$t" "$count"
done

if [ "$into" = "$LIVE_DB" ]; then
    log "restored over the live database $LIVE_DB"
else
    log "done. Swap traffic by renaming databases once the counts look right:"
    log "  psql -d postgres -c 'ALTER DATABASE $LIVE_DB RENAME TO ${LIVE_DB}_old;'"
    log "  psql -d postgres -c 'ALTER DATABASE $into RENAME TO $LIVE_DB;'"
fi
