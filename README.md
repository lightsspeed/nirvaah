# Nirvaah — Personal Finance Management

Nirvaah is a responsive personal finance MVP with a modular fintech dashboard inspired by the supplied visual reference.

## Engineering standards

How this repository is built and reviewed lives in [`docs/engineering/`](docs/engineering/):
coding and API standards, architecture, database rules, security posture, testing
expectations, the assistant's engineering contract, and a Definition of Done
(including the known-debt ratchet). CI runs the checks described in
`TESTING_STANDARDS.md` on every pull request.

## Stack
- Frontend: React 18, Vite, Recharts, Lucide icons
- Backend: FastAPI, SQLAlchemy, JWT authentication
- Database: PostgreSQL in Docker Compose; SQLite fallback for local backend development
- Runtime: Docker Compose

## Features
- User registration and login
- Monthly income and expense tracking
- Transaction listing, filtering and deletion
- Monthly category budgets
- Notes, tasks and a journal that persist server-side (per user, across devices)
- Savings goals
- Manually tracked investments
- Loans and liabilities
- Dashboard cash-flow chart, spending categories and budget progress
- INR formatting and responsive desktop/mobile layout
- **Assistant** — an "Ask Nirvaah" dock that reads every record type (transactions, budgets, goals, investments, liabilities, notes, tasks, journal) and can add, change or remove them on request, running on a local Ollama model

## Run with Docker
Requirements: Docker Engine and Docker Compose plugin.

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD and SECRET_KEY
docker compose up -d --build
```

Open:
- Web application: http://localhost:3001 (nginx serves the SPA and proxies `/api`)
- API for local tooling: http://127.0.0.1:8001 (loopback only)
- Swagger: http://127.0.0.1:8001/docs

The browser only ever talks to `:3001`; nginx forwards `/api/*` to the backend
container, so the database is never reachable from outside the stack.

Stop:
```bash
docker compose down
```


## Versioning & Docker Hub

Nirvaah is at **1.0.0**. One number lives in `frontend/package.json`; `VERSION`
mirrors it for humans and CI, the API reports it at `GET /api/version`, and the
app footer prints it next to the tagline.

Publish images (Docker Hub account `lightsspeed` by default):

```bash
docker login                                   # token, not your password
./release.sh                                   # version from package.json
./release.sh 1.0.1                             # explicit version
NAMESPACE=myorg ./release.sh                   # different account/org
SKIP_PUSH=1 ./release.sh                       # build + tag only
```

Each service is tagged three ways — `1.0.0`, `1.0`, `latest`:

| image | size |
|---|---|
| `lightsspeed/nirvaah-backend` | ~400 MB |
| `lightsspeed/nirvaah-frontend` | ~75 MB |
| `lightsspeed/nirvaah-backup` | ~675 MB |

Run the published stack instead of building locally:

```bash
DOCKER_NAMESPACE=lightsspeed APP_VERSION=1.0.0 docker compose pull
DOCKER_NAMESPACE=lightsspeed APP_VERSION=1.0.0 docker compose up -d
```

(The compose services carry `image:` names, so `pull` fetches the published tags;
`docker compose build` still produces them locally when you want to build.)

### Rebuilding after a code change

`docker compose up -d` **reuses whatever image is already tagged** — it does not
notice that `src/` changed. That is how a stack ends up running month-old code
with a green test suite. Rebuild whenever the source moves:

```bash
docker compose up -d --build            # rebuild the changed service(s), then restart
docker compose build backend            # build only, leave the stack running
docker compose up -d --force-recreate backend   # restart onto the new image
```

`--pull` refreshes the base images as well; the four bases are digest-pinned, so a
plain build keeps using exactly the pinned image and `--pull` only matters after
you bump a digest by hand:

```bash
docker compose build --pull             # after updating a FROM ...@sha256: line
docker buildx imagetools inspect python:3.12-slim   # the digest to pin
```

### Which commit is this image?

Every image carries OCI labels, so the question is one command:

```bash
docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
    lightsspeed/nirvaah-backend:1.0.0
docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
    lightsspeed/nirvaah-frontend:1.0.0
```

Compare that to `git rev-parse HEAD`. `release.sh` fills the revision from the
checkout it builds and the date from the build moment; CI passes the commit SHA;
a bare local build records `unknown` rather than a guess. The labels also cover
`source`, `version` and `created`.

Nothing here deploys anything: `up` and `build` are local Docker only. Publishing
is `release.sh`, which tags and pushes to the registry and stops there.

## Schema migrations

`create_all()` at startup only creates **missing tables** — it never adds an index
to a table that already exists. Schema changes therefore ship as numbered SQL files
in [`backend/migrations`](backend/migrations) and are applied deliberately:

```bash
docker compose run --rm backend python -m app.migrate
```

Each run applies every pending file in one transaction and records it in
`schema_migrations`; a second run is a no-op. On PostgreSQL a failure rolls the
batch back and an advisory lock stops two runners from racing. Nothing is applied
at container start, so a deploy never issues DDL against a live database, and a
freshly created database needs this command once.

## Assistant reliability layer

The assistant is structured so that nothing it says can get ahead of the
database. Four modules carry that contract:

| module | job |
|---|---|
| `app/agent/resolve.py` | decides *which* record a message means: id → exact name → scored token match. Ambiguity is reported, never guessed. |
| `app/agent/execution.py` | every write: resolve → validate → capture before → commit → **read the row back** → compare. Returns `{success, operation, entity_type, entity_id, changes{before,after}, verified, error}`. |
| `app/agent/analytics.py` | deterministic money queries. Returns a status so "you spent ₹0" and "there is no data for that month" can never be confused. |
| `app/agent/planner.py` | scans the question for a category, a month or a span, runs the matching query, and hands the result to the model as `VERIFIED ANALYTICS`. |

Two more pieces make follow-ups work: `chat_focus` (per conversation: the record
"it" refers to, written only by a successful mutation) and `app/agent/obs.py`
(one JSON event per tool call plus counters at `GET /api/chat/metrics`).

A reply can only call something done when the read-back agreed. A reply that
claims a write with no action behind it is retried once, then replaced with
"Nothing was saved". Missing data is never rendered as ₹0.

### Tests

```bash
cd backend
pip install pytest
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -q      # 24 tests
```

The suite runs against a throwaway SQLite database with a scripted model — no
network, no real records. It covers: two tasks in one message, reschedule by
name, pronoun follow-ups, category/month analytics, "which month was highest",
journal-vs-task confusion, false-success blocking, empty months, stale
operation metadata, ambiguous matches, and simulated commit/verification
failures. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids the langsmith plugin, which
fails to load on hosts where an Application Control policy blocks `uuid_utils`.

## Assistant

The **Assistant** page (sidebar → OVERVIEW → Assistant) answers questions about
your own records and can add, change or remove them. Each turn runs through a
LangGraph state graph — `recall → think → act → finish` — with a checkpointer
holding the thread, so follow-ups ("and last month?", "delete that one") resolve
against what was said before.

```bash
ollama pull qwen2.5:3b            # once
# .env (defaults already work on Docker Desktop):
# OLLAMA_URL=http://host.docker.internal:11434
# OLLAMA_MODEL=qwen2.5:3b
docker compose up -d --build
```

- **Reads:** transactions, budgets, goals, investments, liabilities, notes,
  tasks, journal, plus the computed totals and net worth on the dashboard.
- **Writes** are applied through the API; deletes come back as a confirmation
  card naming the exact record, so nothing disappears on one tap.
- **Conversations** are stored in Postgres (`chat_conversations`,
  `chat_messages`), so a thread survives restarts and can be renamed or deleted.
- **Memory** (`chat_memories`): "remember that I prefer UPI under ₹1,000" is kept
  and injected into every later conversation; facts can be added or removed from
  the rail on the Assistant page.
- **Endpoints:** `GET /api/chat/status`, `GET /api/chat/metrics`, `GET|POST /api/chat/conversations`,
  `PATCH|DELETE /api/chat/conversations/{id}`,
  `GET|POST /api/chat/conversations/{id}/messages`,
  `POST /api/chat/conversations/{id}/confirm`, `GET|POST /api/chat/memories`.

### Cloud fallback

When the local model is unreachable — or answers with something the action
parser cannot read — the assistant retries against any OpenAI-compatible
endpoint. The defaults point at DeepSeek:

```bash
# .env
DEEPSEEK_API_KEY=sk-…            # or FALLBACK_API_KEY; empty = local-only
DEEPSEEK_API_URL=https://api.deepseek.com/v1
FALLBACK_MODEL=deepseek-flash
ASSISTANT_FALLBACK=on            # set to off to force local-only
```

**Model picker.** The Assistant rail lists every model it can see — the Ollama
models and the ones the cloud endpoint advertises (fetched from `/models`) —
plus an *Automatic* option (local first, then cloud). Picking one pins it for
that browser; replies are badged with the provider (`local` / `deepseek`) and the
footer names the active model. `GET /api/chat/status` returns the same list under
`models`.
A larger local model (e.g. `ollama pull qwen2.5:7b-instruct` plus
`OLLAMA_MODEL=qwen2.5:7b-instruct`) follows the action format more reliably.

Delete the database volume (destructive — drops notes, tasks and journal):
```bash
docker compose down -v
```

### Persistence
`postgres_data` is a named volume, so transactions, budgets, goals, investments,
liabilities **and the life records (notes, tasks, journal entries)** survive
`docker compose down`, rebuilds and image upgrades. The life records are served
by `/api/notes`, `/api/tasks` and `/api/journal`; the browser keeps a local
cache for instant paint and diffs against Postgres, so a record created on one
device shows up on another and survives a browser wipe.

### A note on names
The product is **Nirvaah**. Browser storage keys still carry the old `moneta_`
prefix (`moneta_token`, `moneta_notes`, `moneta_tasks`, `moneta_events`,
`moneta_theme`, category lists) and the compose project keeps its original
directory name, so renaming cannot orphan an existing volume or wipe local
caches. New code should not introduce fresh `moneta_` identifiers.

### Backups — infrastructure
The bucket and the least-privilege IAM identity are Terraform, in
[`infra/terraform`](infra/terraform/README.md): private bucket, public access
blocked, versioned, SSE-S3, Object Lock (GOVERNANCE, 7 days), lifecycle to
STANDARD_IA/GLACIER_IR, TLS-only bucket policy. The backup container is the only
service attached to the `egress` network — everything else stays internal.

```bash
cd infra/terraform && terraform init && terraform apply
terraform output env_block      # paste into ../.env
```

### Backups — the agent
A `backup` service runs beside the database. Every `BACKUP_INTERVAL_HOURS`
(4 by default) it:

1. `pg_dump --format=custom` the whole database and record a SHA-256 sidecar,
2. restores that archive into a scratch database and compares **every** public
   table — row count and a per-table md5 fingerprint — with the live database. A
   backup that cannot be restored is discarded, not uploaded,
3. fingerprints the **rows** and skips the upload when nothing changed. Hashing
   the dump file itself does not work: pg_dump embeds a timestamp and a random
   token, so the bytes differ every run,
4. uploads to `s3://$S3_BUCKET/$S3_PREFIX/` with the digest in object metadata,
   then verifies the upload with `head-object` (size, checksum metadata) **and**
   downloads the object again to hash it. Only then is the run marked verified,
   and only then does retention run, always keeping one local copy in the
   `backups` volume plus the newest verified remote object,
5. prunes archives older than `BACKUP_RETENTION_DAYS`, keeping the 1st of every
   month for `BACKUP_RETENTION_MONTHS`. A failed run prunes nothing, and the last
   known good backup is never a candidate.

`state/status.json` tracks the latest run (`status`, `last_run`, `last_run_ok`)
and `last_success` separately, so a dead credential turns the healthcheck
unhealthy while the last good copy stays identifiable. Full detail — checks,
lock semantics, IAM scope and the test matrix — is in
[`docs/engineering/BACKUP_AND_DR.md`](docs/engineering/BACKUP_AND_DR.md).

```bash
# run one backup by hand (the arg goes to the entrypoint, not the script path)
docker compose run --rm backup --once
docker compose run --rm backup --status
docker compose run --rm backup --health
docker compose run --rm backup --verify-remote

# restore drill: never restore into `finance` first
docker compose run --rm --entrypoint /backup/restore.sh backup --list
docker compose run --rm --entrypoint /backup/restore.sh backup --file latest.dump
docker compose run --rm --entrypoint /backup/restore.sh backup --file latest.dump --into-live
```

The restore drill verifies the archive's checksum before it runs `pg_restore` and
prints row counts per table; swap the databases by renaming only after they look
right. `--force` only overrides a checksum refusal — it never lets a restore
overwrite the live database without `--into-live`. Cloudflare R2, Backblaze B2
and MinIO all work via `S3_ENDPOINT`; R2 is usually the cheapest for this because
egress is free.

### Disaster recovery — what is actually covered

| Failure | Covered by | Result |
|---|---|---|
| A container crashes or is OOM-killed | `restart: unless-stopped` + healthchecks | back in seconds, no data loss |
| Host reboots | `restart: unless-stopped` | stack comes up on boot |
| Database corrupted / row deleted | last dump (≤ interval old) | RPO ≤ 4 h, RTO ~10 min |
| Host lost entirely | offsite dumps in S3 + this repo | rebuild with `compose up` + `restore.sh` (RTO ~30 min) |
| Ransomware / bad deploy | dated archives + S3 versioning (enable it) | pick an archive from before the event |

`restart: always` is **availability, not recovery**. It cannot help when the
data is wrong, the volume is gone, or the host is dead — those need the dump.

Two things are not in the database and must be backed up separately: `.env`
(`POSTGRES_PASSWORD`, `SECRET_KEY` — without them a restore yields data but no
sessions) and the repo itself. Keep `.env` in a password manager; consider
encrypting archives before upload if the bucket is shared.

### Container hardening
| Control | backend | frontend | db |
|---|---|---|---|
| Runtime user | `app` (uid 1001) | `nginx` (uid 101) | postgres |
| Root filesystem | read-only + tmpfs `/tmp` | read-only + tmpfs `/tmp` | writable volume |
| Capabilities | `ALL` dropped | `ALL` dropped | `ALL` dropped, 5 re-added |
| Privilege escalation | `no-new-privileges` | `no-new-privileges` | `no-new-privileges` |
| Published ports | `127.0.0.1:8001` only | `3001 → 8080` | **none** |
| Limits | 512 MB / 200 pids | 128 MB / 100 pids | 512 MB / 200 pids |
| Healthcheck | `/api/health` | `/` | `pg_isready` |

Networks are split: `app` (frontend ↔ backend) and `data` (backend ↔ db,
`internal: true`), so the web tier cannot route to the database. nginx sends
`server_tokens off`, HSTS-style cache rules, a strict CSP, `X-Frame-Options`,
`X-Content-Type-Options` and `Referrer-Policy`, and the API is same-origin —
no CORS in production.

## Run locally
Backend:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend in another terminal:
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Notes and limitations
- The dashboard balance card currently shows monthly net cashflow (income minus expenses), not a consolidated bank balance. This is labelled accordingly in the interface.
- Historical months in the cash-flow chart currently use illustrative sample values. Replace these with a historical aggregation API before relying on reports.
- Account/bank balance management and transaction-to-account reconciliation are not included in this build.
- Investment values are manually entered and are not live market prices.
- Money columns currently use floating-point storage. Before production, migrate monetary values to PostgreSQL NUMERIC and Python Decimal.
- This is a learning-ready MVP, not a production financial ledger. Add Alembic migrations, automated tests, rate limiting, audit logs, stronger session handling, secrets management, TLS, backups and restore testing before production.
- Secrets come from `.env` (git-ignored). Change `POSTGRES_PASSWORD` and `SECRET_KEY` before any deployment — rotating `SECRET_KEY` invalidates existing sessions by design.
- The API still accepts the token in `localStorage`; move to httpOnly cookies + CSRF tokens before exposing this publicly.
- The backend is the only service that can reach Postgres; keep it that way when adding services.
