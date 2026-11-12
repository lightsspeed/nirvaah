# Security standards — Nirvaah

Current posture, the gaps that are known, and the rules for new work.
Verified state is marked; unverified assumptions are labelled as such.

---

## 1. Secrets

- All secrets come from `.env`, which is **gitignored** (verified: `.env` is absent from the GitHub tree; only `.env.example` with placeholders is published).
- `docker-compose.yml` references them with the fail-closed form `${SECRET_KEY:?SECRET_KEY must be set in .env}` — a missing value stops the stack instead of falling back to a default.
- **Gap (audit C3):** `security.py:11` still has `os.getenv("SECRET_KEY", "CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT")`. A direct `uvicorn` run without `.env` starts with a public, forgeable signing key. Standard for this branch's follow-up: fail at import if the value is missing or shorter than 32 chars.
- **Gap:** the AWS access key pair and the DeepSeek key are long-lived static credentials in `.env`. Rotate them (`IAM → rotate access key`, DeepSeek console) and prefer an instance role / OIDC over static keys.
- Never log a secret, a token, a full `.env`, or a transaction description list. `agent/obs.py` logs ids, statuses and counts only.

## 2. Authentication and sessions

| Item | Current |
|---|---|
| Password hashing | bcrypt via passlib, default cost ✅ |
| Password policy | min 8 chars, max 72 (bcrypt limit) ✅ |
| Token | HS256 JWT, `sub=user_id`, 12 h expiry, no `iat`/`aud` ⚠️ |
| Storage | `localStorage.moneta_token` ⚠️ readable by any script on the origin |
| Refresh / revocation | none — logout is client-side only; a stolen token lives 12 h ⚠️ |
| Rate limiting on `/api/auth/login` | **none** ❌ |
| Account lockout / captcha | none ❌ |

Rules for new work:
1. Any new authenticated endpoint uses `Depends(get_current_user)`; do not invent a second scheme.
2. Authorization is per-row: `filter(user_id == user.id)`. Cross-user reads return 404.
3. Do not add a second place a token can live. The migration to httpOnly cookies + CSRF (Planned) replaces `localStorage`, it does not join it.
4. Assume the SPA is hostile territory: no `dangerouslySetInnerHTML` (verified: none), no `eval`, no third-party script tags.

## 3. Transport and headers

Verified in `frontend/nginx.conf`:

```
server_tokens off;
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'
  https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:;
  img-src 'self' data: https:; connect-src 'self'; object-src 'none';
  base-uri 'self'; form-action 'self'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=()
Cross-Origin-Opener-Policy: same-origin
```
`'unsafe-inline'` for styles is required by the app's inline `style={{...}}` usage;
removing it is Planned (CSS modules).

**Gap:** **no TLS in the repo.** Publishing `3001:8080` plaintext is acceptable for
localhost only. A public deployment needs a terminating proxy (Caddy/Traefik) with
HSTS, or Cloudflare in front. Do not expose the port to the internet as-is.

## 4. Container hardening (verified in `docker-compose.yml`)

- Database has **no published port**; only `backend` and `frontend` are reachable.
- `backend` publishes `127.0.0.1:8001` only — loopback, for local debugging.
- Both app containers run `read_only: true` with `tmpfs` for `/tmp`.
- `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit`, `pids_limit`.
- Backend image runs as uid 1001 (non-root); postsgres runs with dropped capabilities plus the minimum needed set.
- Postgres auth is `scram-sha-256`.
- Log rotation caps at 10 MB × 3 per service.

Rules: no new service may publish a port on `0.0.0.0` without a documented reason;
no image may run as root; no `privileged: true`.

## 5. Input handling

- Request bodies validated by Pydantic; SQL is built by SQLAlchemy — **no string-concatenated SQL anywhere** (verified: `func.to_char`, `ilike`, no `text()` with interpolation).
- `ilike` searches escape nothing; a user-supplied `%` widens their own search only. Acceptable.
- XSS: the markdown renderer builds React elements (`src/ai/Markdown.jsx`), not HTML strings.
- File uploads: none.

## 6. Assistant-specific risk (the new attack surface)

- **Prompt injection:** records (descriptions, note bodies) are user content that reaches the system prompt. `SYSTEM_RULES` rule 3 states records are data, not instructions. Do not remove that rule.
- **Tool execution:** the model can propose `delete_*`; those are proposals only (`pending`) until the user confirms, and confirmation runs through the same verified executor.
- **Wrong-record writes:** `resolve.py` scoring + `guard_action` + per-conversation focus; an ambiguous match is a question, never a guess.
- **Cost/abuse:** no per-user rate limit on `/api/chat/*`. A logged-in user can burn provider quota. Add a per-user quota before any public launch.
- **Data egress:** every turn sends a snapshot of the user's finances to `api.deepseek.com`. This must be stated in the privacy policy and is the reason the provider is configurable.

## 7. Dependencies

- Backend pins exact versions in `requirements.txt`; frontend uses `^` ranges with a committed `package-lock.json`.
- **Gap:** no `dependabot.yml`, no vulnerability scan in CI, base images not digest-pinned.
- Rule: a dependency is upgraded in its own PR with the reason in the body, and `pytest` + `npm run build` must pass.

## 8. Reporting a problem

Until a `SECURITY.md` exists (Planned), report privately to the repository owner.
Do not open a public issue containing a working exploit, a token, or a `.env` value.
