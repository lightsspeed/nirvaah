# API standards — Nirvaah

Derived from the routes that exist in `backend/app/main.py` and
`backend/app/agent/api.py`. Where the current API does not meet a rule, the
deviation is named instead of pretending.

---

## 1. Shape

| Rule | Current state |
|---|---|
| All routes under `/api` | ✅ yes (`/api/health`, `/api/chat/...`) |
| JSON request and response only | ✅ yes (no form posts, no multipart) |
| Path names plural, lowercase, hyphen-free | ✅ `/api/transactions`, `/api/chat/conversations` |
| Resource id in the path for single-record operations | ✅ `/api/transactions/{item_id}` |
| Actions that are not CRUD use a sub-resource | ✅ `/api/chat/conversations/{id}/confirm` |
| Version prefix (`/api/v1`) | ❌ **absent** — flat `/api`. Adding a prefix is a breaking change; decide before the first external consumer |

## 2. Authentication

- `Authorization: Bearer <jwt>` on every route except `/api/health`, `/api/version`, `/api/auth/register`, `/api/auth/login`.
- The token is HS256, `sub = user_id`, 12 h expiry (`security.py:create_access_token`).
- Every handler that touches user data takes `user=Depends(get_current_user)` and **must filter by `user.id`**. A query without that filter is a bug, not a style issue.
- Ownership failures return **404**, not 403 (do not confirm that a row exists for someone else) — `owned()` already behaves this way.

## 3. Request validation

- Every request body is a Pydantic model in `schemas.py` (money routes) or in the router module (assistant: `MessageIn`, `ConversationIn`, `MemoryIn`).
- Constraints live in the schema, not the handler: `Field(gt=0)`, `pattern=r"^\d{4}-\d{2}$"`, `min_length=8`.
- Domain invariants that a schema cannot express stay in the handler and raise `HTTPException(400, "...")` with a sentence a user could read.
- Assistant tool actions are validated twice: by `agent/execution.py` field builders and by the reply contract. Never loosen that to a single check.

## 4. Response bodies

- Success: the resource itself (`txn_dict`, `_message_out`, list of dicts). No `{"data": ...}` envelope.
- Error: FastAPI's `{"detail": "..."}`. Keep messages lowercase-start, no stack traces, no internal ids.
- Deletes: `{"deleted": true}` (money routes) or the verified action result (assistant).
- Mutations that can be confirmed by a human **must** return enough to render the outcome: `summary`, and for the assistant `changes{before,after}`, `verified`.

## 5. Status codes in use

| Code | When |
|---|---|
| 200 | read, update, delete-as-action |
| 201 | not used — creates return 200 with the record |
| 400 | malformed or impossible request ("kind must be income or expense") |
| 401 | missing/invalid token (`get_current_user`) |
| 404 | record not found **or not owned** |
| 409 | duplicate email on register |
| 422 | Pydantic validation failure (automatic) |
| 503 | LLM provider unreachable (`ProviderError`) |

Do not invent new codes without adding them to this table.

## 6. Lists

- Today every list endpoint returns **all** matching rows: `/api/transactions`, `/api/notes`, `/api/tasks`, `/api/journal`.
- Filters are query parameters (`month`, `start_date`, `end_date`, `kind`, `category`, `search`) and are applied server-side.
- **Standard to adopt (Planned):** `?limit=` (default 100, max 500) plus `?before_id=` cursor; response keeps the plain array and adds `X-Has-More` / `next_before` as a header or a sibling field. Do not introduce offset pagination — the data is append-heavy and ordered by date.

## 7. Time and money

- Dates are ISO `YYYY-MM-DD` strings; months are `YYYY-MM`.
- Server timezone is UTC; "today" for the user is derived from the server clock (`date.today()`), **not** from a user timezone — a documented gap for non-IST users.
- Money is rendered by the server only in assistant replies (`₹1,20,500` grouping, `fields.inr()`). API payloads carry raw numbers; formatting is the client's job.

## 8. Idempotency and retries

- Creates are not idempotent today: retrying `POST /api/transactions` duplicates a row. Clients must not auto-retry a POST.
- Life records are the exception — the client supplies the `id`, so a retried `POST /api/tasks` with the same id is an upsert by primary key.
- **Standard:** any new POST that mutates money must accept an `Idempotency-Key` header or take a client-generated id.

## 9. Assistant endpoint contract

`POST /api/chat/conversations/{id}/messages` returns the assistant message:

```json
{
  "id": 145, "role": "assistant", "content": "Moved it to 21 November 2026.",
  "provider": "cloud", "model": "deepseek-flash",
  "applied": [{"operation": "update_task", "entity_type": "task", "entity_id": "d83…",
               "verified": true, "changes": {"due": {"before": "2026-11-14", "after": "2026-11-21"}},
               "summary": "Updated task \"Pay maintenance\""}],
  "pending": [], "failed": [], "steps": ["recall","think","act","finish"],
  "verified": true, "degraded": "", "note": "", "runner": "langgraph", "model": "deepseek-flash"
}
```

Rules that must not regress:
- `applied` contains **only** actions that were committed *and* read back.
- `pending` is for deletes awaiting confirmation; `failed` carries `error`.
- A turn that changed nothing returns empty `applied`/`pending`/`failed` — never the previous turn's actions.

## 10. Documentation

FastAPI generates OpenAPI at `/docs`. It is enabled in production today; decide
whether to expose it publicly (Planned). Every new route needs a one-line
`summary=` so the generated docs are readable.
