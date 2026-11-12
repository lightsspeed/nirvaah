# Definition of Done — Nirvaah

A change is done when every box that applies is ticked **and can be shown**, not
described. "It should work" is not evidence.

---

## 1. Every change

- [ ] `git status` shows only intended files; no `.env`, no `dist/`, no `node_modules/`, no `*.db`.
- [ ] Commit is one concern, message says *why*.
- [ ] No new secret, token or credential in the diff.
- [ ] No debug `print`, no commented-out block, no `TODO` without an owner and a task.
- [ ] If behaviour changed, at least one test changed with it (or the reason it cannot be tested is in the PR).

## 2. Backend change

- [ ] `ruff check --select E9,F63,F7,F82,F821 app tests` clean (blocking gate).
- [ ] `ruff check app tests` does not add **new** findings beyond the recorded baseline.
- [ ] `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -q` passing.
- [ ] New endpoints use `Depends(get_current_user)` and filter by `user_id`.
- [ ] New request bodies are Pydantic models with constraints.
- [ ] Queries that touch mutable data read back what they wrote when the response
      claims success.

## 3. Frontend change

- [ ] `npm run build` passes.
- [ ] `npm run lint` does not add new errors (warnings allowed, counted).
- [ ] New hooks are unconditional (`rules-of-hooks` is an error).
- [ ] New effects clean up their listeners/timers.
- [ ] The change is checked in the browser in **both themes** and at 1440px and 390px.
- [ ] No new global CSS selector fighting `design.css`; styling lives in the component's own file.

## 4. Database change

- [ ] Model change, migration, and any backfill are in the same PR (Alembic is Planned; until then the schema is `create_all` and the change is explicit in the PR description).
- [ ] New index added alongside the query that needs it, verified with `EXPLAIN ANALYZE` on real data.
- [ ] New relationship has an `ondelete`; new business-unique combination has a constraint.
- [ ] A restore drill was considered for anything that rewrites data (`pg_restore` into a scratch DB).

## 5. Assistant change

- [ ] Failing test written first and seen to fail for the right reason.
- [ ] The mutation path still reads back after commit (`agent/execution.py`).
- [ ] Prompt rules 20–24 intact; any new rule has a server-side enforcement.
- [ ] `false_success` counter stays at 0 in the live check.
- [ ] Live check done against a throwaway user seeded from a copy of real data, then that user deleted.
- [ ] Real user's row counts recorded before and after (users / transactions / tasks).

## 6. Release

- [ ] `VERSION`, `frontend/package.json`, `APP_VERSION` agree.
- [ ] `GET /api/version` reports the same number from the running container.
- [ ] Images built, tagged, pushed; local digest == registry digest.
- [ ] The running container is on that digest (recreate if it was an intermediate build).
- [ ] `docker compose ps` healthy for db/backend/frontend.
- [ ] Backup ran since the last schema or data change.

## 7. Known debt on this branch (the ratchet)

Recorded so it is paid down deliberately instead of by surprise. Each item has a
task; flipping a CI step from advisory to blocking happens in that task.

| # | Debt | Measure | Exit condition |
|---|---|---|---|
| 1 | ~~Dead, broken Ollama transport in `ai.py` (`_post_json`, `ollama_chat`, `OLLAMA_MODEL`, 9 × `F821`)~~ — **retired on `feature/engineering-foundation`**, together with its `per-file-ignores` entry. `F821` is clean repo-wide and the ignore is gone | `ruff check --select F821 app tests` | ✅ done |
| 2 | ~~Legacy executor, its private helpers and the `execute_action` wrapper in `ai.py`~~ — **retired on `feature/engineering-foundation`**: executor and its private helpers removed in `574a6dc`, the stranded coercion helpers (`_money`, `_inr`, `_num`, `_text`, `_date`, `_month`, `_tags`), `STOPWORDS`, `import uuid` and the `Any`/`datetime` imports removed in `81d0656`, and the unused `execute_action` compatibility wrapper plus its dead imports removed in `7db3c9d`. `ai.py` 901 → 426 lines | `ruff check app/ai.py` | ✅ done |
| 3 | ~~`backend/app/main.py` `crud_routes()` — empty function~~ — **retired on `feature/engineering-foundation`**: no decorator, no caller, no registration; removed with no change to the 48 routes | route count | ✅ done |
| 4 | `frontend/src/style.css` — 1,587 lines, never imported | `grep -r "style.css" frontend/src` | deleted |
| 5 | Backend lint baseline | 79 findings, 20 files unformatted (same numbers as `CODING_STANDARDS.md`) | 0 findings; then CI step becomes blocking |
| 6 | Frontend lint baseline | `App.jsx:1556` hook-order error **fixed in `42ed91a`**; the 31 warnings reported after that commit remain (unused vars, `exhaustive-deps`) | 0 errors ✅; 0 warnings before the step can enforce `--max-warnings=0` |
| 7 | Frontend format baseline | 14 files | `npm run format` once, in its own commit |
| 8 | No migrations | `create_all` only | Alembic baseline + `alembic upgrade head` in the image entrypoint |
| 9 | Money as `double precision` | 9 columns | `Numeric(14,2)` + backfill |
| 10 | Unpaginated list endpoints | 4 routes | cursor pagination + composite indexes |

## 8. What "done" is not

- Not "the tests pass" alone — the tests may not cover the change.
- Not "the model said it worked" — only a read-back counts.
- Not "CI is green" while a step is advisory and failing; report the number.
- Not "pushed" — this branch is local only until a human says otherwise.
