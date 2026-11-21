# Deploy

| File | Purpose |
|---|---|
| `docker-compose.prod.yml` | Overlay for the AWS host: Caddy TLS, frontend port bound to loopback, frontend tag pinned independently. |
| `Caddyfile` | One public origin; automatic Let's Encrypt certificates. |
| `deploy.ps1` | Builds the server `.env` from the local one, uploads, pulls, starts, verifies. |

See `infra/aws/README.md` for the architecture, cost and runbook.

Local development still uses the root `docker-compose.yml` unchanged.

## PWA notes

The app is installable on Android out of the box:

- `frontend/public/manifest.webmanifest` — `id`, `display: standalone`,
  `display_override`, 192/512 icons, maskable icon, `start_url`, theme colour.
- `frontend/public/sw.js` — app-shell cache, network-first navigations,
  `/api/` never cached. Registered from `main.jsx` in production builds only.
- `nginx.conf` serves `.webmanifest` as `application/manifest+json` and sends
  `Cache-Control: no-store` for `sw.js`, so updates land on the next load.
- `InstallPrompt.jsx` shows the in-app "Install Nirvaah" banner on the
  `beforeinstallprompt` event; it stays hidden when already installed or
  dismissed, and on iOS (which has no equivalent API).

Install on Android: open `https://nirvaah.deployone.cloud` in Chrome →
menu → **Add to Home screen** (or tap the in-app Install button). Launching
from the home screen runs it standalone with the offline shell.

Bumping the app shell requires bumping `SHELL` in `sw.js` (`nirvaah-shell-v3`,
…) so old caches are dropped on activate.
