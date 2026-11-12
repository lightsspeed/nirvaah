#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Nirvaah restore.
#
#   ./restore.sh --list                       show local + remote archives
#   ./restore.sh --file latest.dump           restore into a scratch DB and report
#   ./restore.sh --file latest.dump --into finance --force
#
# Restoring into the live database is refused unless --force is passed: the
# safe default is a scratch database you can inspect before swapping.
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

log() { printf '%s  %s\n' "$(date -u '+%H:%M:%SZ')" "$*"; }

s3() {
    if [ -n "$S3_ENDPOINT" ]; then
        aws --endpoint-url "$S3_ENDPOINT" --region "$AWS_REGION" s3 "$@"
    else
        aws --region "$AWS_REGION" s3 "$@"
    fi
}

file=""
into="nirvaah_restore_check"
force=false

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
        --force) force=true; shift ;;
        *) log "unknown argument: $1"; exit 2 ;;
    esac
done

[ -n "$file" ] || { log "usage: restore.sh --file <archive> [--into <db>] [--force]"; exit 2; }

path="$WORK_DIR/$file"
if [ ! -f "$path" ] && [ -n "$S3_BUCKET" ]; then
    log "fetching $file from S3"
    s3 cp "s3://$S3_BUCKET/$S3_PREFIX/$file" "$path" --only-show-errors || { log "not found locally or remotely"; exit 1; }
fi
[ -f "$path" ] || { log "archive not found: $path"; exit 1; }

log "verifying archive"
pg_restore --list "$path" >/dev/null || { log "archive is not restorable"; exit 1; }

if [ "$into" = "${PGDATABASE:-finance}" ] && [ "$force" != true ]; then
    log "refusing to overwrite the live database without --force"; exit 1
fi

log "creating database $into"
psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$into\";" >/dev/null
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$into\";" >/dev/null

log "restoring into $into"
pg_restore --dbname="$into" --no-owner --no-privileges --exit-on-error "$path"

log "row counts in $into:"
for t in users transactions budgets goals investments liabilities notes tasks journal_entries deletions; do
    count=$(psql -d "$into" -t -A -c "SELECT count(*) FROM $t;" 2>/dev/null || echo 'n/a')
    printf '  %-16s %s\n' "$t" "$count"
done

log "done. Swap traffic by renaming databases once the counts look right:"
log "  psql -d postgres -c 'ALTER DATABASE finance RENAME TO finance_old;'"
log "  psql -d postgres -c 'ALTER DATABASE $into RENAME TO finance;'"
