# Testing standards — Nirvaah

What runs today, what it proves, and what must be added before the suite can be
trusted as a release gate.

---

## 1. Current suite (verified on this branch)

```
backend/tests/conftest.py                  fixtures: throwaway SQLite DB, seeded user,
                                           scripted model (no network)
backend/tests/test_assistant_reliability.py  26 tests
```

```
$ cd backend
$ PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -q
26 passed
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is required on this Windows host: the
`langsmith` pytest plugin imports `uuid_utils`, which an Application Control
policy blocks. The flag is harmless elsewhere and is used in CI for the same
deterministic plugin set.

**What the 26 tests cover** (assistant only):

| Scenario | Test |
|---|---|
| Two tasks in one message, verified, no duplicate | `test_a_create_two_tasks` |
| A repeat request is a new record, not a silent dupe | `test_a_retry_does_not_duplicate` |
| Reschedule by name, `before/after` recorded | `test_b_reschedule_updates_the_right_task` |
| Pronoun follow-up hits the focused record | `test_c_followup_updates_the_focused_task` |
| Category spend for a named month from SQL | `test_d_category_month_uses_the_database` |
| Fuzzy category name ("dining out") resolves | `test_d_category_name_is_fuzzy_matched` |
| Peak month for a category | `test_e_max_month_for_category` |
| Journal entry is not completable as a task | `test_f_journal_entry_is_not_completable` |
| Claim without action is blocked / retried | `test_g_false_success_is_blocked`, `test_g_claim_with_retry_succeeds` |
| Empty month is `no_data`, never ₹0 | `test_h_empty_month_is_reported_as_missing_not_zero` |
| Due-date follow-up, no duplicate | `test_i_due_date_followup` |
| A question turn reports no changes | `test_j_question_turn_reports_no_changes` |
| Ambiguous name asks instead of guessing | `test_k_ambiguous_target_asks_instead_of_updating`, `test_k_unique_name_still_resolves` |
| Commit failure is honest | `test_l_commit_failure_is_honest` |
| Read-back mismatch is honest | `test_l_verification_failure_is_honest` |
| Delete proposes, then verifies | `test_delete_needs_confirmation_then_verifies` |
| Resolver: exact / not found / request-word stripping | three `test_resolver_*` |
| Analytics zero vs missing, peak month | `test_analytics_distinguish_zero_from_missing` |
| Relative month resolution | `test_planner_resolves_relative_months` |
| June totals add up | `test_totals_still_add_up` |
| Invented category is named, not zeroed | `test_unknown_category_is_not_a_zero`, `test_real_phrase_in_a_description_is_not_called_unknown` |

**Not covered today:** every money route (auth, transactions, budgets, dashboard,
analytics), the sync/tombstone flow, and the entire frontend. That is the honest
gap; the suite protects the assistant's contract, nothing else.

## 2. Rules for new tests

1. **Never touch production data.** Tests build their own database from `models.Base.metadata` (see `conftest.py`). A test that needs the real database is not a test.
2. **No network.** Stub the provider (`scripted` fixture) rather than calling DeepSeek. A test that needs the live model belongs in the evaluation suite (§4), not in `pytest`.
3. **Assert the database, not the reply.** After a mutation, re-read the row (`db.expire_all()` first) and assert the persisted value. A green assertion on a string is not proof a write happened.
4. **Name the scenario in the test name** (`test_h_empty_month_is_reported_as_missing_not_zero`), so a failure reads as a behaviour, not a line number.
5. **One behaviour per test.** A test that fails should point at one rule.
6. **A bug fix ships with the test that would have caught it** — no exceptions for "obvious" fixes.

## 3. What must be added (planned, in order)

1. **API tests** — `httpx.AsyncClient` + `TestClient` against the FastAPI app with a SQLite session override:
   auth (register/login/401/404 on foreign ids), transaction CRUD, dashboard totals, sync version + tombstones.
2. **Money-maths tests for `analytics.py`** beyond the two that exist: month boundaries, DST-free date handling, categories with zero rows, very large and very small amounts.
3. **Frontend tests** — Vitest + Testing Library, starting with pure logic (`life/store.js` merge/tombstone functions) and one render test per page after the `App.jsx` split.
4. **Contract test for the assistant HTTP surface** — the shape in `API_STANDARDS.md §9` (applied/verified/pending) asserted end-to-end with the scripted model.

## 4. Evaluation (the assistant is probabilistic — unit tests are not enough)

Deterministic tests prove the machinery, not the answers. Add a **golden set**:

- 30–50 real questions with the expected figure computed by SQL at assert time
  (never hardcoded — the data changes).
- Run nightly against the real provider, not per PR (cost and flakiness).
- Assert on numbers and entity ids, not phrasing.
- Fail the run when the success rate drops below the recorded baseline
  (start at whatever the first run measures; ratchet upward).

Covered question families: single-month category spend, peak month per category,
month-over-month, savings rate, merchant/recurring, "not found" cases, and
mutations followed by a verifying read.

## 5. Commands

```bash
# backend
cd backend
ruff check app tests                                  # configured rule set (advisory tier)
ruff check --select E9,F63,F7,F82,F821 app tests      # correctness gate (blocking)
ruff format --check app tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests -q

# frontend
cd frontend
npm run lint
npm run format:check
npm run build
```

## 6. CI behaviour

`.github/workflows/ci.yml` runs on every pull request:

| Step | Blocking | Why |
|---|---|---|
| backend correctness gate (`E9,F63,F7,F82,F821`) | ✅ | clean today; regressions are real bugs |
| backend full lint + format check | ⚠️ advisory | 91 findings, 20 files unformatted — see the ratchet in `DEFINITION_OF_DONE.md` |
| backend tests | ✅ | 26 passing today |
| frontend lint | ⚠️ advisory | one real hooks-order defect (App.jsx:1556) plus 31 warnings |
| frontend build | ✅ | catches import/JSX breakage |

An advisory step that fails marks the run with a warning and prints the counts;
it does not block the PR **yet**. Each advisory step gets a follow-up task and
flips to blocking in the same PR that clears its baseline.
