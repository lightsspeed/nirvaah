#!/usr/bin/env bash
# ── Nirvaah release ─────────────────────────────────────────────────────────
# Builds the three images, tags them with the release version, the minor line
# and latest, then pushes them to Docker Hub.
#
#   ./release.sh                      # version from frontend/package.json
#   ./release.sh 1.0.1                # explicit version
#   NAMESPACE=myorg ./release.sh      # different Docker Hub account/org
#   SKIP_PUSH=1 ./release.sh          # build and tag only
#
# Requires: docker login (a token, not your password).
set -euo pipefail

cd "$(dirname "$0")"

VERSION="${1:-$(python -c "import json;print(json.load(open('frontend/package.json'))['version'])")}"
NAMESPACE="${NAMESPACE:-${DOCKER_NAMESPACE:-lightsspeed}}"
MINOR="${VERSION%.*}"

SERVICES=(backend frontend backup)
echo "▶ Nirvaah ${VERSION}  →  docker.io/${NAMESPACE}/nirvaah-*"

# Truthful build metadata: the revision actually checked out here, and the moment
# the build ran. If this is not a git checkout, record "unknown" rather than a
# plausible-looking value.
GIT_REVISION="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
BUILD_DATE="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  revision ${GIT_REVISION}"

APP_VERSION="$VERSION" DOCKER_NAMESPACE="$NAMESPACE" \
    GIT_REVISION="$GIT_REVISION" BUILD_DATE="$BUILD_DATE" \
    docker compose build "${SERVICES[@]}"

for svc in "${SERVICES[@]}"; do
    base="${NAMESPACE}/nirvaah-${svc}"
    for tag in "${VERSION}" "${MINOR}" latest; do
        docker tag "docker.io/${NAMESPACE}/nirvaah-${svc}:${VERSION}" "${base}:${tag}"
    done
    if [[ "${SKIP_PUSH:-0}" != "1" ]]; then
        docker push --all-tags "${base}"
    fi
done

echo
echo "✔ pushed:"
for svc in "${SERVICES[@]}"; do
    echo "   docker.io/${NAMESPACE}/nirvaah-${svc}:${VERSION} (+ ${MINOR}, latest)"
done
