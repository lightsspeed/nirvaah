# Base images are pinned by digest as well as tag. A tag can be re-pointed at a new
# build at any time; a digest cannot. To bump one deliberately:
#
#   docker buildx imagetools inspect python:3.12-slim
#   # copy the top-level "Digest:" (the multi-arch index), not a per-platform one,
#   # then update the FROM line below. Keep the family and major version.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Unprivileged runtime account, created before any code lands in the image.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --no-create-home --shell /usr/sbin/nologin app

# The app resolves "today" through zoneinfo, which reads the IANA database from the
# filesystem. Install it explicitly rather than inheriting it by luck: without it
# every zone except UTC raises, and the timezone header route answers 400.
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Build metadata. GIT_REVISION comes from the checkout being built (compose,
# release.sh or CI); it stays "unknown" rather than a fabricated value when no
# revision is available.
ARG APP_VERSION=1.0.0
ARG GIT_REVISION=unknown
ARG BUILD_DATE=unknown
ARG SOURCE_URL=https://github.com/lightsspeed/nirvaah
ENV APP_VERSION=$APP_VERSION

LABEL org.opencontainers.image.title="Nirvaah API" \
      org.opencontainers.image.description="Nirvaah personal finance backend (FastAPI)" \
      org.opencontainers.image.source=$SOURCE_URL \
      org.opencontainers.image.revision=$GIT_REVISION \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.created=$BUILD_DATE

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=4s --start-period=25s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
