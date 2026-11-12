# Architecture — Nirvaah

What exists today, as built. Nothing here is aspirational; future work is
marked **Planned** and collected at the end.

---

## 1. Runtime topology

```
                       browser (React SPA)
                              │  same origin, /api/* proxied
                              ▼
        ┌──────────────────────────────────────────┐
        │ frontend  nginx:1.27-alpine  :8080       │   published 3001:8080
        │  • serves dist/ (immutable asset cache)  │   read_only, cap_drop
        │  • CSP + security headers                │
        └────────────────┬─────────────────────────┘
                         │ proxy_pass http://backend:8000/api/
                         ▼
        ┌──────────────────────────────────────────┐
        │ backend  FastAPI + uvicorn  :8000        │   published 127.0.0.1:8001 only
        │  app/main.py        36 routes            │   read_only, non-root uid 1001
        │  app/agent/*        assistant (12 routes)│
        └────────────────┬─────────────────────────┘
                         │ psycopg3
                         ▼
        ┌──────────────────────────────────────────┐
        │ db  postgres:16-alpine                   │   no published port
        │  volume postgres_data                    │   scram-sha-256
        └──────────────────────────────────────────┘

        backup (profile "backup") — pg_dump → checksum → S3, restore-verified
        LLM: api.deepseek.com (egress only; no local model in the chain)
```

Four compose services: `db`, `backend`, `frontend`, `backup`.
`docker-compose.yml` is the single source of truth for ports, limits and health.

## 2. Backend layout

```
backend/app/
  main.py            36 routes: auth, dashboard, transactions, budgets, goals,
                     investments, liabilities, cashflow, analytics, tx range,
                     notes/tasks/journal CRUD, sync version, deletions
  models.py          14 SQLAlchemy models
  schemas.py         Pydantic request bodies (money routes only)
  security.py        bcrypt hashing, HS256 JWT, get_current_user dependency
  database.py        engine + SessionLocal + Base
  ai.py              snapshot builder, system prompt, action catalogue,
                     guard_action, backwards-compatible execute_action
  agent/
    api.py           /api/chat/*: conversations, messages, confirm, memories, metrics
    graph.py         LangGraph node definitions + run_turn
    providers.py     DeepSeek client (ask / models), ProviderError
    execution.py     verified mutations (resolve → validate → commit → read back)
    resolve.py       record matching + scoring + ambiguity
    analytics.py     deterministic money queries with explicit status codes
    planner.py       question → which analytics call to run
    focus.py         per-conversation "what does 'it' mean"
    obs.py           structured events + counters
    reply.py         reply claims detection, id stripping, currency normalisation
    fields.py        coercion helpers shared by prompt and executor
    months.py        month resolution used by the snapshot
```

### Request path (money route)
`HTTP → Depends(get_current_user)` (JWT → `users` row) → Pydantic validation →
`db.query(...)` filtered by `user_id` → dict → JSON.

Ownership is enforced per query (`filter(model.user_id == user.id)`) or via
`owned()` in `main.py:22`. There is no global row-level policy.

### Request path (assistant)
```
POST /api/chat/conversations/{id}/messages
  → api.send_message            persists the user turn
  → graph.run_turn
      recall   snapshot (ai.build_snapshot)
               planner.analyse → analytics query
               focus.get → CURRENT FOCUS block
               memories (chat_memories)
      think    providers.ask → {"reply", "actions"}
               claim-without-action → one retry
      act      focus.apply → guard_action → execution.execute (verified)
               deletes → dry_run → pending (UI confirms)
      finish   reply only from verified results; blockers for false claims
  → api.send_message            persists the assistant turn + meta JSON
  → frontend onChanged()        reloads money pages, dispatches REMOTE_CHANGE
```

The assistant is the only place with a read-back verification contract. Money
routes written by the UI commit and trust the database to accept the write.

## 3. Frontend layout

```
frontend/src/
  App.jsx           3,909 lines — auth screen, shell, every money page, modals
  AssistantPage.jsx 396  – assistant page (rail + thread + composer)
  GlobalSearch.jsx  163  – ⌘K search over transactions/notes/tasks
  design.css       6,041 – the last stylesheet loaded, wins most conflicts
  additions.css    3,108
  theme.css        1,605
  styles.css       1,482
  life/life.css    1,586
  assistant.css      514
  tokens.css         226  – colours, type scale, radii
  style.css        1,587  – NOT imported anywhere (dead)
  life/
    store.js         564  – localStorage-first store + server sync (7 s poll)
    TasksPage.jsx    612  – tasks, checklist UI, quick add
    NotesPage.jsx    360
    JournalPage.jsx  466
    ui.jsx           323  – shared inputs/selects
  ai/Markdown.jsx     56  – small markdown renderer (no innerHTML)
```

State model: `localStorage` is the offline cache; the server is the source of
truth. `store.js` polls `/api/sync/version` (a fingerprint of counts + max
`updated_at`), and re-hydrates collections when it changes. Deletes are
**tombstones** (`deletions` table) so an offline device cannot resurrect a record.

## 4. Data model (14 tables)

`users` → `transactions`, `budgets`, `goals`, `investments`, `liabilities`,
`notes`, `tasks`, `journal_entries`, `deletions`, `chat_conversations`,
`chat_messages`, `chat_memories`, `chat_focus`.
String primary keys (`uuid4`) on life records so a client can create offline and
keep the same id; autoincrement ints on money records.

Every table has `user_id` with an index. There are **no composite indexes, no
unique constraints beyond `users.email`, and no `ON DELETE` cascades** — the
schema is created by `Base.metadata.create_all()` with no migration history.

## 5. Deployment

- `docker compose up -d` on a single host; images published as
  `lightsspeed/nirvaah-{backend,frontend,backup}` via `./release.sh`.
- `VERSION`, `frontend/package.json` and `/api/version` carry the release number.
- TLS termination and a public hostname are **not** part of this repo yet.
- Backups: `backup/backup.sh` (cron in its own container) dumps to S3, verifies
  by restoring into a scratch database and comparing row counts.
- Terraform in `infra/terraform/` provisions the bucket + IAM only (local state,
  not applied by CI).

## 6. Planned (not built — do not document as if it exists)

- **Migrations** (Alembic) and `Numeric` money columns.
- **Pagination** on list endpoints; composite indexes.
- **Frontend split** into routed pages with a data layer; Vitest + Testing Library.
- **Streaming** assistant replies; request-scoped tracing middleware.
- **CI/CD pipeline**: this branch adds CI checks only; no deployment workflow.
