FROM postgres:16-alpine

# pg_dump + pg_restore come from the base image; aws-cli handles S3 (and any
# S3-compatible target such as Cloudflare R2, Backblaze B2 or MinIO).
RUN apk add --no-cache aws-cli tzdata     && addgroup -S backup     && adduser -S -G backup -h /backup backup

WORKDIR /backup
COPY --chown=backup:backup backup.sh restore.sh ./

# Docker seeds a fresh named volume from the image, ownership included.
# sed guards against a Windows checkout reintroducing CRLF line endings.
RUN sed -i 's/$//' backup.sh restore.sh     && chmod 0755 backup.sh restore.sh     && mkdir -p /backup/work /backup/state     && chown -R backup:backup /backup/work /backup/state     && chmod 0750 /backup/work /backup/state

USER backup

ENTRYPOINT ["/backup/backup.sh"]
