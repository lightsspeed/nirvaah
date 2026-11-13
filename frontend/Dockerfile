# ── build ────────────────────────────────────────────────────────────────
# Base images are pinned by digest as well as tag; a tag can be re-pointed at a
# new build at any time, a digest cannot. To bump one deliberately:
#
#   docker buildx imagetools inspect node:22-alpine
#   # copy the top-level "Digest:" (the multi-arch index), then update this line.
FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build
WORKDIR /app

# The browser talks to one origin: nginx proxies /api to the backend, so the
# API port is never published and CORS is not needed in production.
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

COPY package*.json ./
# Lockfile only. A stale lock is a build failure, not a silent unlocked install.
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ── serve ────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

# Build metadata for the runtime image. GIT_REVISION comes from the checkout being
# built (compose, release.sh or CI); "unknown" when no revision is available —
# never a fabricated value.
ARG APP_VERSION=1.0.0
ARG GIT_REVISION=unknown
ARG BUILD_DATE=unknown
ARG SOURCE_URL=https://github.com/lightsspeed/nirvaah
ENV APP_VERSION=$APP_VERSION

LABEL org.opencontainers.image.title="Nirvaah" \
      org.opencontainers.image.description="Nirvaah personal finance frontend (nginx)" \
      org.opencontainers.image.source=$SOURCE_URL \
      org.opencontainers.image.revision=$GIT_REVISION \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.created=$BUILD_DATE

RUN rm -f /etc/nginx/conf.d/default.conf \
    && rm -rf /usr/share/nginx/html/*

COPY nginx.conf /etc/nginx/nginx.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

# nginx runs unprivileged on 8080; the only writable path is /tmp.
USER nginx
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
