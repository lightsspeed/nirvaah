#!/bin/sh
# Test double: a psql that refuses to answer the table-catalogue query.
#
# The fail-closed guard fires when discovery returns nothing, which in production
# happens if that one query fails (permissions, a broken client, a database that
# is not reachable for reads while still dumpable). Every other psql call passes
# through so the dump, the restore and the row comparisons still run.
for arg in "$@"; do
    case "$arg" in
        *pg_tables*)
            echo "psql: error: could not read the table catalogue" >&2
            exit 1
            ;;
    esac
done
exec /usr/local/bin/psql "$@"
