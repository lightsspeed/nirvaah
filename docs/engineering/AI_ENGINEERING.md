# AI engineering — Nirvaah assistant

Rules for changing anything on the assistant path (`backend/app/ai.py`,
`backend/app/agent/*`). The failure mode to design against is not "the model is
wrong" but "the model said something that was not true about the database".

---

## 1. The contract

One model call per turn, one JSON object:

```json
{"reply": "…", "actions": [{"op": "add_task", "text": "Pay rent", "due": "2026-11-14"}]}
```

- No tool-calling API, no function schemas. A single JSON contract is cheaper and
  easier to validate than a tool picker, and it works with any OpenAI-compatible
  endpoint.
- `parse_model_output` is forgiving (fences, prose around the object, `action`
  instead of `op`) but never invents actions.
- The reply text is data, not truth. Only `actions` can change anything.

## 2. Verified execution (do not weaken)

`agent/execution.execute()` — every write:

```
resolve target → validate fields → capture before → commit
   → expire the identity map → re-read the row → compare → result
```

Result shape (`API_STANDARDS.md §9`) carries `success`, `operation`,
`entity_type`, `entity_id`, `changes{before,after}`, `verified`, `error`.

Rules:
1. A reply may only say "added/updated/deleted" for an action whose
   `verified` is true.
2. If `_commit` fails, `_read_back` returns nothing, or a field disagrees with
   what was asked, the turn reports the failure — `graph.finish` uses the
   executor's error string, not the model's sentence.
3. Adding an op means adding a field builder **and** a test that asserts the
   persisted row, not the reply.
4. Never `db.commit()` inside an op without reading the row back.

## 3. Deterministic money

The model never does arithmetic.

- `analytics.py` computes every figure with SQL and returns a **status**:
  `ok`, `unknown_category`, `no_data`, `no_data_for_category`.
- `ok` with `0.0` is the only legitimate zero.
- `summary`/`categories` figures are quoted verbatim (rule 22); the prompt forbids
  recomputation, and `graph.finish` replaces any reply that puts a rupee figure on
  a non-`ok` status.
- `planner.analyse()` decides which query runs, from the message text. It never
  guesses a category: a name that matches nothing in the ledger and nothing in any
  description becomes `unknown_category`, not zero.

When adding an analytics capability: add the function with an explicit status,
add it to the planner's routing, add a prompt line naming it, and add a test that
proves the zero/missing distinction for it.

## 4. Context

- `chat_focus` (Postgres) holds the one record the conversation is about: type,
  id, label, and the operation that set it. It is written **only** after a
  verified mutation.
- A follow-up with a pronoun and no name of its own inherits that id
  (`focus.apply`, marked `from_focus` so the word-overlap guard stands aside).
- A message that names another record ignores the focus.
- The checkpointer (`InMemorySaver`) is process memory; history is re-seeded from
  `chat_messages` after a restart. **Every turn-scoped channel must be reset in
  `run_turn`'s payload** — otherwise a question inherits the previous turn's
  `applied` list and the UI shows a phantom "2 changes saved".

## 5. Matching

`resolve.py` scores candidates: exact name 100 → exact field 96 → prefix 88 →
containment 76 → token overlap 30–80. `ACCEPT_SCORE = 55`.

- Request words are stripped (`STOPWORDS`: "reschedule", "task", "priority", "high"…), so "reschedule my servicing task" scores on "servicing".
- A tie at the top score is **ambiguous** → ask, never pick.
- Below `ACCEPT_SCORE` → not found → say so.
- `guard_action` uses the same scorer; if you change one threshold, change both.

## 6. Honesty rules in the prompt (rules 20–24)

20. changes happen only through actions; the app verifies them.
21. tasks, journal entries and notes are different entities; never convert or
    mark a journal entry done.
22. `VERIFIED ANALYTICS` is the only source for those figures; a non-`ok` status
    means say so, never zero.
23. `CURRENT FOCUS` defines "it"/"that"/"the same one".
24. act only on a record whose name matches; several matches → ask; none → say so.

Prompt rules are a first line, not the guarantee. Each has a server-side
enforcement behind it (see §2, §3, §4, §5). **A new rule that matters must get a
server check, or it will drift.**

## 7. Failure taxonomy (what to log and what to fix)

| Symptom | Counter | Where to look |
|---|---|---|
| claim with no action | `claim_retry` | `graph.think` retry path, prompt rules 20 |
| reply claims a change, nothing applied | `false_success` | `graph.finish` |
| commit rejected | `commit_failed` | `execution._commit`, DB logs |
| commit fine, read-back differs | `verify_failed` | `execution._read_back` |
| ambiguous target | `ambiguous_target` | `resolve.ACCEPT_SCORE`, `STOPWORDS` |
| analytics threw | `analytics_error` | `planner.analyse` |
| zero shown on missing data | `false_success` / `zero_on_missing_data` | `graph.finish` money guard |

`GET /api/chat/metrics` exposes the counters. A non-zero `false_success` is an
incident, not a warning.

## 8. Cost and latency

- Snapshot ≈ 14 k chars (~3.5 k tokens) + analytics block; measured reply times
  1–4 s on `deepseek-flash`.
- **Known inefficiency:** each turn loads the whole transaction table several
  times (`build_snapshot`, `planner.available_range`, `analytics._rows`,
  `text_exists`). Acceptable at 754 rows; it must become SQL aggregation before
  the data grows.
- No streaming and no cancellation: the request holds a worker thread for the
  whole call. Bounded retry with backoff is Planned; only the claim-without-action
  retry exists today.

## 9. Changing the assistant safely

1. Write the failing test first (`tests/`), run it, watch it fail for the right reason.
2. Change the smallest surface: planner heuristic, field builder, prompt rule.
3. Run the suite; then run the live check by hand against a **throwaway user** with a copy of real data, and delete that user afterwards.
4. Record anything the model did not do correctly as a new test, not a new paragraph of prompt.
5. Never ship a prompt change without checking `false_success` stays at zero.
