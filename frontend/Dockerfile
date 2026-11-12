# ── build ────────────────────────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app

# The browser talks to one origin: nginx proxies /api to the backend, so the
# API port is never published and CORS is not needed in production.
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

COPY package*.json ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY . .
RUN npm run build

# ── serve ────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf \
    && rm -rf /usr/share/nginx/html/*

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html

# nginx runs unprivileged on 8080; the only writable path is /tmp.
USER nginx
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
