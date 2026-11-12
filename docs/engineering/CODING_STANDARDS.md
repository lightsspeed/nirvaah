# Coding standards — Nirvaah

Applies to `backend/` (Python) and `frontend/` (JavaScript/React).
Status: **current practice**, with the gaps stated honestly at the bottom.

---

## 1. Python (backend)

### Tooling
| Tool | Command | Purpose |
|---|---|---|
| Ruff lint | `ruff check app tests` | defects + consistency |
| Ruff format | `ruff format app tests` | formatting |
| Pytest | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests -q` | tests |

Configuration lives in `backend/pyproject.toml`. Two tiers:

- **Blocking in CI** — `ruff check --select E9,F63,F7,F82,F821`: syntax errors,
  undefined names, bad forward references. This set is clean today; keep it clean.
- **Advisory in CI** — the full configured set (`E4,E7,E9,F,I,B,UP`, minus
  `B008` for FastAPI `Depends`) plus `ruff format --check`. 81 findings as of
  this branch; see `DEFINITION_OF_DONE.md` for the ratchet.

`B008` is ignored on purpose: `Depends(...)` in a default argument is FastAPI's
documented idiom, not a bug.

### Style that the codebase already follows
- Line length **110** (`line-length` in `pyproject.toml`); formatter wraps, no `E501` policing.
- Double quotes; 4-space indent; imports sorted, two blank lines after the import block.
- Type hints on new functions (`def execute(db: Session, user, action: dict) -> dict:`). `user` stays untyped where it is a model instance already validated by the dependency.
- Absolute imports from `app.*` inside the package (`from .. import models`, `from . import obs`).
- One module, one responsibility. The assistant is the model for this: `resolve.py` (matching), `execution.py` (writes), `analytics.py` (money maths), `planner.py` (question → query), `focus.py` (context), `obs.py` (events).

### Rules
1. **No business logic in route handlers.** `main.py` handlers do: validate with a schema → call the domain function → return a dict. The assistant path already follows this (`agent/execution.py`); the money routes mostly do not yet.
2. **Money is never a bare float in new code.** Until the schema migration lands, round at the boundary (`round(x, 2)`) and never do arithmetic on raw `float` from two sources. Target type: `Numeric(14, 2)` / `Decimal`.
3. **Every write that a human or the assistant reports as "done" must be verifiable.** Use `agent/execution.execute()` or an equivalent read-back; do not `db.commit()` and assume.
4. **Catch narrowly.** `except Exception` is allowed only at a boundary where losing the request is worse than swallowing it (graph execution, focus writes, logging) and must log via `obs.event`.
5. **No bare `pass` on an error path.** If a failure is acceptable, say why in a comment.
6. **No `print`.** Use `logging` / `obs.event`.
7. **Config comes from the environment**, read once at import (`os.getenv`), never scattered through request handlers.
8. **Dead code is deleted, not commented out.** The repo already carries the cost of this rule being skipped (see below).

### Known deviations (measured on this branch — do not fix by mass rewrite)
```
ruff check (configured set) : 81 findings
  E702 41  multiple statements on one line ("db.commit(); db.refresh(row)")
  I001 16  unsorted imports
  F401 11  unused imports
  E741  6  ambiguous variable name ("l")
  E701  3  multiple statements with colon
  B904  2  raise without "from" inside except
  UP017/UP035 2  datetime.utcnow / deprecated import
ruff format --check : 20 of 22 files would be reformatted
ruff check --select E9,F63,F7,F82,F821 : clean
```
The 48 `E702` sites are the semi-colon one-liners; `ruff format` fixes them mechanically. Land that as a standalone "format only" commit, never mixed with a behaviour change.

---

## 2. JavaScript / React (frontend)

### Tooling
| Tool | Command | Config |
|---|---|---|
| ESLint | `npm run lint` | `frontend/eslint.config.js` (flat config, v9) |
| Prettier | `npm run format` / `npm run format:check` | `.prettierrc.json`, `.prettierignore` |

- 4-space indent, single quotes in JS, double quotes in JSX (`jsxSingleQuote: false`), semicolons, width 120, LF.
- CSS and HTML are excluded from Prettier for now (see `.prettierignore`) — reformatting 16k lines of hand-tuned CSS is its own project.

### Style that the codebase already follows
- Function components, hooks only, no class components.
- `const`/`let`, arrow functions for handlers, optional chaining for possibly-missing data.
- One page per file under `src/` or `src/life/`, with its own CSS file.
- API access through the shared `axios` instance (`api` prop), not raw `fetch` (the life store is the documented exception — it uses `fetch` for its sync loop).
- State that must survive reload goes in `localStorage` under the `moneta_*` keys; server state is re-fetched, never cached as truth.

### Rules
1. **Hooks are unconditional.** No hook may sit below an early `return`. `react-hooks/rules-of-hooks` is an **error** and blocks CI when clean.
2. **Effects need a cleanup** if they subscribe, start a timer, or attach a listener (see `life/store.js` for the pattern).
3. **Never store a token anywhere but the existing `localStorage.moneta_token`** until the httpOnly-cookie migration lands. Don't add a second auth mechanism.
4. **Money formatting** goes through one helper, not inline `₹` interpolation in each component.
5. **No new global CSS selectors** that fight `design.css`; new styling belongs to the component's own stylesheet.
6. **Prop drilling beyond two levels** is a signal to extract a context or split the component.

### Known deviations (measured on this branch)
```
npx eslint src     : 1 error, 31 warnings
  react-hooks/rules-of-hooks   1  (App.jsx:1556 — useMemo below the auth-screen early return)
  no-unused-vars              26
  react-hooks/exhaustive-deps  5
npx prettier --check : 14 files
```
The single error is a genuine defect, not style: the hook count differs between the auth render and the app render. It is reported here and in the audit; it is **not** fixed in this task.

---

## 3. Commits

- One concern per commit. A formatting commit is never mixed with a behaviour commit.
- Subject: imperative, ≤ 72 chars. Body explains *why*, not *what*.
- Reference the audit finding when fixing one (`Fixes audit H6`).
- No secrets, no `.env`, no `dist/`, no `node_modules/` — `.gitignore` already covers these; `git diff --staged` before every commit.

## 4. Reviews

A reviewer must be able to answer, from the diff alone: what behaviour changed,
which files carry the verification, and how it was tested. If a change touches a
write path, the reviewer checks that the reply can only claim success after a
read-back.
