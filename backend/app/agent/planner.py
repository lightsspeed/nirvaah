"""Question → deterministic query.

The model is good at phrasing and bad at arithmetic and recall. So the code
decides *what* to compute: the message is scanned for a category, a month or a
time span, the matching analytics call is made, and the result travels with the
prompt as verified facts. The model's job is to explain those numbers.

When nothing matches, this returns `intent: None` and the turn behaves exactly
as before — no question is made worse by the planner failing.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from ..timeutil import iso_utc, utcnow
from . import analytics
from . import obs
from .resolve import normalise

MONTH_NAMES = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\b", re.I)
# "List the grocery spends" asks for the records; "how much did I spend on
# groceries" asks for a figure. These two vocabularies decide which one it is.
_LIST_CUES = re.compile(
    r"\b(list|show|display|detail|details|breakdown|each|every|give me|which transactions|what are)\b",
    re.I,
)
_SUMMARY_CUES = re.compile(
    r"\b(how much|how many|average|avg|total|totals|highest|lowest|most|least|max|min|maximum|"
    r"minimum|biggest|largest|top|compare|compared|versus|vs|trend|percentage|percent|rate|budget|"
    r"remaining)\b",
    re.I,
)
_LIST_NOUN = r"(?:transactions?|spends?|spending|expenses?|purchases?|payments?|bills?)"
_LIST_NOUN_RE = re.compile(r"\b" + _LIST_NOUN + r"\b", re.I)
# The single word that names what is being listed: "grocery spends", "restaurant
# transactions", "grocery spending". Multi-word categories come from the pool.
_LIST_PHRASE_RE = re.compile(r"\b([a-z][a-z'&-]{2,})\s+" + _LIST_NOUN + r"\b", re.I)
_STOPWORDS = {
    "all", "any", "my", "our", "the", "these", "those", "this", "that", "last", "next",
    "recent", "latest", "newest", "oldest", "first", "every", "each", "of", "and", "down",
    "me", "give", "show", "list", "display",
    "monthly", "total", "income", "expense", "expenses", "spend", "spends", "spending",
}
LIST_LIMIT = 40
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_LAST_N_RE = re.compile(r"\blast\s+(\d{1,2})\s+months?\b", re.I)


def resolve_month(message: str, today: date | None = None) -> str | None:
    """'June' → 2026-06, 'last month' → 2026-10, 'june 2025' → 2025-06."""
    today = today or date.today()
    text = normalise(message)

    if re.search(r"\bthis month\b|\bcurrent month\b", text):
        return today.strftime("%Y-%m")
    if re.search(r"\blast month\b|\bprevious month\b", text):
        return analytics.shift_month(today.strftime("%Y-%m"), -1)
    if re.search(r"\bmonth before\b", text):
        return analytics.shift_month(today.strftime("%Y-%m"), -2)

    year_match = _YEAR_RE.search(text)
    named = _MONTH_RE.search(text)
    if named:
        month = MONTH_NAMES[named.group(1).lower()]
        if year_match:
            year = int(year_match.group(1))
        else:
            year = today.year
            # "June" said in February means last June, not one in the future.
            if month > today.month:
                year -= 1
        return f"{year:04d}-{month:02d}"

    iso = re.search(r"\b(20\d{2})-(\d{2})\b", text)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}"
    return None


def _months_back(message: str) -> int | None:
    match = _LAST_N_RE.search(normalise(message))
    if match:
        return max(1, min(36, int(match.group(1))))
    if re.search(r"\blast six months\b", normalise(message)):
        return 6
    if re.search(r"\blast three months\b", normalise(message)):
        return 3
    if re.search(r"\byear to date\b|\bthis year\b|\bytd\b", normalise(message)):
        return None
    return None


def _requested_category_phrase(message: str) -> str | None:
    """The category a correction or switch names, if it names one."""
    match = _CORRECTION_PHRASE.search(message) or _SWITCH_PHRASE.search(message)
    if not match:
        return None
    phrase = match.group("phrase").strip(" .?!,'\"")
    phrase = _PHRASE_PREFIX.sub("", phrase)
    phrase = _PHRASE_TAIL.sub("", phrase).strip()
    if not phrase or re.search(r"\d", phrase):
        return None
    if resolve_month(phrase) is not None:
        # "no, I meant April" is a period, not a category.
        return None
    if len(phrase.split()) > 3:
        return None
    return phrase


def _clean_term(term: str) -> str:
    """Strip the period and the question words off one side of a comparison."""
    term = term.strip(" .,?!'\"")
    month = _MONTH_RE.search(term)
    if month:
        term = term[: month.start()]
    term = _TERM_STOP.sub("", term)
    term = _PHRASE_PREFIX.sub("", term)
    return term.strip(" .,?!'\"")


def _split_comparison(message: str) -> tuple[str, str] | None:
    """The two category names in "compare X vs Y", when both look like names."""
    text = _COMPARE_LEAD.sub("", message or "", count=1).strip()
    parts = _COMPARE_SEP.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    left, right = _clean_term(parts[0]), _clean_term(parts[1])
    for term in (left, right):
        if not term or len(term) > 40 or re.search(r"\d", term) or len(term.split()) > 3:
            return None
        if resolve_month(term) is not None:      # "compare May and June" is months
            return None
    return left, right


def _month_names(text: str) -> list[str]:
    found = re.findall(r"\b(" + "|".join(MONTH_NAMES) + r")\b", text, re.I)
    return [name.lower() for name in found]


def _singular(token: str) -> str:
    """A crude, predictable singular: groceries -> grocery, bills -> bill."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


# "make it a task", "and delete the last one" — a change of records, not a
# question. The lead verb (or an explicit pronoun) plus the absence of any
# analytics wording is what separates the two; "add up my spending" and
# "show me my spending and delete it" stay questions.
_WRITE_LEAD = re.compile(
    r"^\s*(?:(?:and|then|also|now|please|ok|okay|hey)\s+)*"
    r"(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
    r"(?:add|create|update|change|move|reschedule|delete|remove|complete|mark|set|rename|remember|"
    r"log|make)\b", re.I)
_WRITE_IDIOM = re.compile(r"\b(?:add|sum|count)\s+up\b|\bbreak\s+down\b", re.I)
# "I spent ₹1,500 on groceries today." — in a bookkeeping assistant a first-person
# report of money moving *is* the write. It needs a subject, a money verb and an
# amount: "I spent too much last month" is a remark, not a record (Task 28.2).
_MONEY_REPORT = re.compile(
    r"^\s*(?:please\s+|ok\s+|okay\s+|so\s+|and\s+|also\s+)*"
    r"(?:i|we)\s+(?:(?:just|also|recently|already|have|had|finally)\s+)*"
    r"(?:spent|paid|bought|purchased|earned|received|got\s+paid|sold|withdrew|deposited|made)\b"
    r"[^0-9]{0,40}\d",
    re.I)
_ANALYTICS_MARKER = re.compile(
    r"\b(?:compare|comparing|comparison|versus|vs|how much|how many|total|totals|average|avg|"
    r"list|show|display|which|what|where|breakdown|trend|merchants?)\b", re.I)


def _is_write_request(text: str) -> bool:
    """A request to change records — not a question that merely uses a write verb."""
    if _WRITE_IDIOM.search(text) or _ANALYTICS_MARKER.search(text):
        return False
    # A reported transaction is the write itself: no analytics, no new context.
    if _MONEY_REPORT.search(text):
        return True
    if not _WRITE_CUE.search(text):
        return False
    return bool(_WRITE_LEAD.search(text) or _DEICTIC.search(text))


def _listing_facts(found: dict, category, phrase, month, kind) -> dict:
    """One shape for every transaction listing, whatever asked for it."""
    rows = found.get("transactions") or []
    return {
        "status": found.get("status"),
        "month": month,
        "category": category,
        "text": phrase,
        "kind": kind,
        "count": found.get("count", 0),
        "total": found.get("total", 0.0),
        "shown": len(rows),
        "truncated": len(rows) < int(found.get("count") or 0),
        "transactions": [
            {"date": row["date"], "amount": row["amount"], "category": row["category"],
             "description": row["description"], "payment_method": row["paid_with"]}
            for row in rows
        ],
    }


def _listing_phrase(text: str) -> str | None:
    """The noun being listed, when it is not one of the user's categories."""
    match = _LIST_PHRASE_RE.search(text)
    if not match:
        return None
    phrase = match.group(1).strip(" .?!,'")
    if not phrase or phrase in _STOPWORDS or re.search(r"\d", phrase):
        return None
    return phrase


def _wants_extremes(text: str) -> bool:
    return bool(re.search(r"\b(highest|maximum|max|most|top|biggest|largest)\b", text)) or bool(
        re.search(r"\b(lowest|minimum|min|least|smallest)\b", text))


def _object_of_spending(text: str) -> str | None:
    """Pull the thing being spent on out of 'how much did I spend on X in June'."""
    match = re.search(
        r'\b(?:how much )?(?:did i |do i |have i )?(?:spend|spent|pay|paid|cost)\w*\s+(?:on|for)\s+(?:the\s+)?(.+?)(?:\s+in\s+|\s+during\s+|\s+for\s+|$)',
        text,
        re.I,
    )
    if not match:
        return None
    phrase = match.group(1).strip(" .?!,")
    phrase = re.sub(r"\b(this|last|next|previous|that)\s+\w+$", "", phrase).strip()
    return phrase or None


# The thread's analytics filters live one turn at a time. They are read back on
# the next request (assistant message meta) and expired after a few turns so an
# old topic cannot quietly answer a new question.
CONTEXT_TTL_TURNS = 6
# "make it high priority", "change its due date" — a record request, not an
# analytics one. chat_focus owns those; ambiguity here would block a write the
# user clearly asked for.
_WRITE_CUE = re.compile(
    r"\b(add|create|update|change|move|reschedule|delete|remove|complete|mark|set|rename|"
    r"remember|make|assign|log)\b", re.I)

# "compare Groceries vs Dining Out", "which is higher, Fuel or Electricity?"
_COMPARE_CUE = re.compile(
    r"\b(?:compare|compares|compared|comparing|comparison|versus|vs|higher|lower|bigger|larger|"
    r"smaller)\b", re.I)
_COMPARE_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:compare|comparing|comparison of)\s+"
    r"|^\s*(?:which|what)\s+(?:is|was|had|has)\s+(?:the\s+)?(?:higher|lower|bigger|larger|smaller)"
    r"\s*,?\s*", re.I)
_COMPARE_SEP = re.compile(r"\s+(?:vs|versus|against|with|and|or)\s+", re.I)
_TERM_STOP = re.compile(
    r"\b(?:in|on|for|during|from|this|last|previous|next|current|expenses?|spending|spends?|"
    r"totals?|transactions?|payments?|bills?)\b.*$", re.I)
_PERIOD_COMPARISON = re.compile(
    r"\b(?:than|versus|vs|compared (?:to|with))\s+(?:the\s+)?(?:last|previous)\s+(?:month|year)\b"
    r"|\b(?:this|current)\s+month\b.{0,40}\b(?:last|previous)\s+month\b", re.I)

# "what about fuel?", "and April?" — a switch that names one dimension.
_SWITCH_CUE = re.compile(r"^\s*(?:what|how)\s+about\b|^\s*and\b", re.I)
# "no, I meant restaurants" / "and my electricity bill?" name a category. When it
# is not one of the user's, the query must ask rather than widen to everything.
_CORRECTION_PHRASE = re.compile(
    r"\b(?:i meant|i mean|meant|instead of|rather than)\s+(?P<phrase>[a-z][a-z &'-]{1,40})", re.I)
_SWITCH_PHRASE = re.compile(
    r"^\s*(?:and|what about|how about)\s+(?P<phrase>[a-z][a-z &'-]{1,40})", re.I)
_PHRASE_PREFIX = re.compile(r"^(?:the|my|our|some|any|all)\s+", re.I)
_PHRASE_TAIL = re.compile(
    r"\s+(?:ones?|transactions?|spends?|spending|expenses?|payments?|bill|bills)$", re.I)

# "those", "them", "the same one" — a reference with no words of its own.
_DEICTIC = re.compile(
    r"\b(it|its|that|those|these|them|they|the same|same one|the last one)\b", re.I)
# "no, I meant fuel" — the user is correcting a dimension we already have.
_CORRECTION = re.compile(r"\b(no|nope|not|i meant|i mean|actually|rather|instead)\b", re.I)
# "overall", "in total" — the user is stepping out of the thread on purpose.
_ALL_CATEGORIES_CUE = re.compile(
    r"\ball (?:the |my |our |these |those )?(?:(?:income|expense) )?(?:expenses?|transactions?|"
    r"spends?|spending|payments?|income|expense)\b|\ball categories\b", re.I)
# "overall" / "in total" mean all time, but only when no period is named:
# "everything from September" is all categories in September.
_ALL_TIME_CUE = re.compile(
    r"\b(overall|in total|everything|across all|altogether)\b", re.I)
_ALL_CUE = re.compile(f"(?:{_ALL_CATEGORIES_CUE.pattern})|(?:{_ALL_TIME_CUE.pattern})", re.I)
# A question about a dimension (merchant, average…) is a follow-up even when it
# names neither the category nor the month.
_DIMENSION_Q = re.compile(
    r"\b(merchant|largest|biggest|highest|lowest|most|least|recurring|subscription|trend|"
    r"compare|average|avg|total|how much|how many|spend|spent|expense|expenses)\b", re.I)
# "that month", "the other one" — a month reference we cannot pin down.
_VAGUE_MONTH = re.compile(r"\b(other month|that month|the other one|some other month|another month)\b", re.I)
# "Which category did I spend the most on?", "show my top 5 spending categories",
# "rank my expenses by category" — a ranking *across* categories, so the single
# category a thread was carrying is never the subject (Task 28.3).
_RANK_CUE = re.compile(
    r"\b(?:which|what)\s+categor(?:y|ies)\b[^?]{0,40}\b(?:most|highest|biggest|largest|top)\b"
    r"|\b(?:most|highest|biggest|largest)\b[^?]{0,25}\bcategor(?:y|ies)\b"
    r"|\btop\b[^?]{0,20}\bcategor(?:y|ies)\b"
    r"|\bcategor(?:y|ies)\b[^?]{0,20}\b(?:rank|ranking|ranked|breakdown|wise)\b"
    r"|\brank\b[^?]{0,30}\b(?:expenses?|categor(?:y|ies))\b",
    re.I)
_RANK_LIMIT = re.compile(r"\btop\s+(\d{1,2})\b", re.I)
# "Is this expense unusual?", "unusually high", "much higher than normal",
# "outlier" — a question about individual expenses against their own history.
_UNUSUAL_CUE = re.compile(
    r"\bunusual(?:ly)?\b"
    r"|\b(?:much|far|way)\s+(?:higher|bigger|larger)\s+than\s+(?:normal|usual|typical|average|before)\b"
    r"|\babnormally\b|\boutliers?\b|\bout of the ordinary\b",
    re.I)
_RUPEE_AMOUNT = re.compile(r"₹\s*([\d,]+(?:\.\d{1,2})?)")
_RECENT_REFERENCE = re.compile(
    r"\b(?:this|that|the last|the latest)\s+(?:one|expense|transaction|charge|payment|bill)\b",
    re.I)
_KIND_INCOME = re.compile(r"\bincome\b|\bsalary\b|\bearned\b|\breceived\b", re.I)
_KIND_EXPENSE = re.compile(r"\bspend|\bspent\b|\bspending\b|\bexpense|\bcost\b|\bpaid\b|\bpurchase|\bbill", re.I)


def _mentioned_categories(text: str, pool: list[str]) -> list[str]:
    """Which of the user's real categories this text names, in pool order."""
    mentioned = [c for c in pool if normalise(c) and normalise(c) in text]
    if mentioned:
        return mentioned
    for candidate in pool:
        tokens = [t for t in normalise(candidate).split() if len(t) >= 4]
        if tokens and all(t in text or _singular(t) in text for t in tokens):
            mentioned.append(candidate)
    return mentioned


def resolve_followup(message: str, prior: dict | None, today: date | None = None, *,
                     pool: list[str] | None = None, turn: int | None = None) -> dict:
    """Work out which analytics filters this message means.

    Explicit words in the message always win. A recognised follow-up inherits
    only the dimensions it leaves out — a month keeps the category, a correction
    keeps the period — so "what about May?" stays on Groceries and "no, I meant
    fuel" stays in April. Nothing financial is carried: filters only, never
    figures or rows.
    """
    today = today or date.today()
    text = normalise(message)
    pool = pool or []
    month = resolve_month(message, today)
    mentioned = _mentioned_categories(text, pool)
    kind = "income" if _KIND_INCOME.search(text) else ("expense" if _KIND_EXPENSE.search(text) else None)

    deictic = bool(_DEICTIC.search(text))
    correction = bool(_CORRECTION.search(text))
    all_cue = bool(_ALL_CUE.search(text))
    # All time only when the message names no period of its own.
    all_time = bool(_ALL_TIME_CUE.search(text)) and not month
    writing = bool(_WRITE_CUE.search(text))
    switch = bool(_SWITCH_CUE.search(message))
    # A write ("and delete it") is never a category request.
    requested_category = None if writing else _requested_category_phrase(message)
    # A pronoun alone is not an analytics question: "it is done" is about a record.
    # Only ask for clarification when the message is also asking about spending.
    analytics_question = bool(_LIST_NOUN_RE.search(text) or _SUMMARY_CUES.search(text)
                              or _DIMENSION_Q.search(text))

    expired = False
    if isinstance(prior, dict) and turn is not None and prior.get("turn") is not None:
        try:
            if int(turn) - int(prior["turn"]) > CONTEXT_TTL_TURNS:
                prior, expired = None, True
        except (TypeError, ValueError):
            prior = None

    category = mentioned[0] if mentioned else None
    comparison_target = mentioned[1] if len(mentioned) > 1 else None
    followup = False
    reason = "explicit" if (category or month) else "none"

    if all_cue:
        if all_time:
            reason = "user asked for the whole picture"
        else:
            # All categories is a change of scope, not of period: the month the
            # thread is already on survives unless the message names another.
            category = None
            comparison_target = None
            if not month and isinstance(prior, dict):
                month = prior.get("month")
                kind = kind or prior.get("kind")
            followup = bool(month)
            reason = "all categories, kept the period" if month else "all categories"
    elif isinstance(prior, dict) and (prior.get("category") or prior.get("month")):
        if category and month:
            reason = "explicit category and month (new question)"
        elif category:
            if correction or deictic or switch:
                month = month or prior.get("month")
                kind = kind or prior.get("kind")
                followup = bool(month)
                reason = "corrected category, kept the period"
        elif month:
            category = prior.get("category")
            kind = kind or prior.get("kind")
            followup = bool(category)
            reason = "month changed, kept the category"
        elif deictic or _DIMENSION_Q.search(text):
            category = prior.get("category")
            month = prior.get("month")
            kind = kind or prior.get("kind")
            followup = bool(category or month)
            reason = "follow-up on the previous question"

    # A correction or switch keeps the period even when the category it names
    # is not one the user has: the month is a separate dimension.
    if isinstance(prior, dict) and (correction or switch) and not month:
        month = prior.get("month")

    # A comparison asks about a period the user did not restate, so it inherits
    # the thread's month — even when one of the two categories turns out not to
    # exist, so the clarification still says which period it is about. An
    # explicit month wins, and a reset or expired thread has none to give.
    wants_comparison = bool(_COMPARE_CUE.search(text)) and not writing
    if (comparison_target or wants_comparison) and not month and isinstance(prior, dict):
        month = prior.get("month")
        followup = bool(month)
        if month:
            reason = "comparison kept the period"

    if correction and not followup and not (category or month):
        reason = "correction with nothing to correct"

    ambiguous = False
    question = None
    if deictic and not (category or month) and analytics_question and not writing:
        ambiguous = True
        question = ('Which transactions do you mean? Tell me the category and month — '
                    'for example "Groceries in April".')
        reason = "reference with no usable context"
    elif _VAGUE_MONTH.search(text) and not month:
        ambiguous = True
        question = "Which month do you mean?"
        reason = "month reference that cannot be pinned down"

    return {
        "category": category,
        "month": month,
        "kind": kind,
        "comparison_target": comparison_target,
        "requested_category": requested_category,
        "followup": followup,
        "ambiguous": ambiguous,
        "question": question,
        "expired": expired,
        "all_categories": all_cue and not all_time,
        "reset": all_time,
        "turn": prior.get("turn") if isinstance(prior, dict) else None,
        "reason": reason,
    }


def _next_context(resolved: dict, intent: str | None, prior: dict | None, turn: int | None) -> dict | None:
    """The filters to remember for the next turn — no figures, no rows."""
    if resolved.get("reset"):
        return None
    if intent in ("clarify", "unknown_category"):
        # The question could not be answered, so the thread it came from must survive.
        return prior if isinstance(prior, dict) else None
    # A merchant or listing answer has no filters to remember, but its shape is
    # what a later "what about June?" needs, so those turns are remembered too.
    keeps_shape = intent in ("merchants", "list_transactions", "category_ranking")
    if intent and (resolved.get("category") or resolved.get("month") or keeps_shape):
        return {
            "intent": intent,
            "category": resolved.get("category"),
            "month": resolved.get("month"),
            "kind": resolved.get("kind"),
            "comparison_target": resolved.get("comparison_target"),
            "turn": turn,
            "updated_at": iso_utc(utcnow()),
        }
    return prior if isinstance(prior, dict) else None


def analyse(db: Session, user, message: str, today: date | None = None,
            context: dict | None = None, turn: int | None = None) -> dict:
    """Return {"intent", "facts", "context"} — facts is None when no query applies."""
    today = today or date.today()
    text = normalise(message)
    pool = analytics.categories(db, user)

    # A category only counts when it is one of this user's real categories.
    mentioned = _mentioned_categories(text, pool)
    resolved = resolve_followup(message, context, today, pool=pool, turn=turn)
    category = resolved["category"]
    month = resolved["month"]
    kind = resolved["kind"]

    def done(intent, query, facts):
        """Attach the filters this turn leaves behind for the next one."""
        return {"intent": intent, "query": query, "facts": facts,
                "context": _next_context(resolved, intent, context, turn)}

    # A change of records runs no query and leaves the analytics thread alone.
    if _is_write_request(text):
        return done(None, {}, None)

    # An unusual-expense question is about individual outliers against each
    # category's own history. It runs before the category and ambiguity checks:
    # "is this expense unusual?" is answerable, not a request for clarification,
    # and "unusual expenses" is not a category the user was naming.
    if _UNUSUAL_CUE.search(text) and not _WRITE_CUE.search(text):
        named_amount = _RUPEE_AMOUNT.search(message)
        probe = None
        if named_amount:
            try:
                probe = Decimal(named_amount.group(1).replace(",", ""))
            except InvalidOperation:
                probe = None
        explicit_category = mentioned[0] if mentioned else None
        scope_year = None
        if not month:
            named_year = _YEAR_RE.search(text)
            if named_year:
                scope_year = int(named_year.group(1))
            elif re.search(r"\bthis year\b|\bcurrent year\b|\byear\b(?!s)", text):
                scope_year = today.year - 1 if re.search(r"\blast year\b", text) else today.year
        facts = analytics.unusual_expenses(
            db, user, month=month, year=scope_year, category=explicit_category,
            recent=bool(_RECENT_REFERENCE.search(message)), probe_amount=probe)
        return done("unusual_expenses",
                    {"month": month, "year": scope_year, "category": explicit_category,
                     "probe": probe is not None}, facts)

    # A category the user named but does not have must never become "all
    # categories": ask, and keep the period the thread was already on.
    requested = resolved.get("requested_category")
    if requested and not category:
        matched = analytics.match_categories(db, user, requested)
        if matched:
            category = matched[0]
        else:
            return done("unknown_category", {"phrase": requested, "month": month},
                        {"status": "unknown_category", "category": requested,
                         "requested_category": requested, "scope": None, "month": month,
                         "known_categories": pool,
                         "message": (f'You have no category called "{requested}" — I cannot '
                                     f'answer that without inventing one.')})

    # A reference we cannot resolve is a question, not a guess.
    if resolved["ambiguous"]:
        return done("clarify", {"question": resolved["question"]},
                    {"status": "ambiguous", "question": resolved["question"],
                     "message": resolved["question"]})

    # A ranking question asks across categories. It is answered before the
    # single-category aggregates, and it drops whatever category the thread was
    # carrying — the question is which category, not how much of one.
    if _RANK_CUE.search(text) and not _WRITE_CUE.search(text) \
            and not (_COMPARE_CUE.search(text) and resolved.get("comparison_target")):
        top = _RANK_LIMIT.search(text)
        limit = int(top.group(1)) if top else 5
        rank_month, rank_year = month, None
        if not rank_month:
            named_year = _YEAR_RE.search(text)
            if named_year:
                rank_year = int(named_year.group(1))
            elif re.search(r"\bthis year\b|\bcurrent year\b|\byear\b(?!s)", text):
                rank_year = today.year - 1 if re.search(r"\blast year\b", text) else today.year
        resolved.update({"category": None, "comparison_target": None, "month": rank_month})
        facts = analytics.category_ranking(db, user, month=rank_month, year=rank_year,
                                           limit=limit, kind=kind or "expense")
        return done("category_ranking",
                    {"month": rank_month, "year": rank_year, "limit": limit}, facts)

    # A spend question about something that is not in the ledger at all.
    # Answering it with a figure (even a zero) is a fabrication, so name it.
    if not mentioned and re.search(r"\b(spend|spent|paid|cost)\b", text):
        phrase = _object_of_spending(normalise(message))
        if phrase and len(phrase) <= 40 and not re.search(r"\d", phrase) \
                and not analytics.text_exists(db, user, phrase):
            if not analytics.match_categories(db, user, phrase):
                return done(
                    "unknown_category",
                    {"phrase": phrase, "month": month},
                    {
                        "status": "unknown_category",
                        "category": phrase,
                        "month": month,
                        "known_categories": pool,
                        "message": (f"You have no category or transaction called \"{phrase}\" — I cannot give a figure for it."),
                    })

    # A listing request is answered with the records, not with a total. It is
    # checked before the category+month aggregate so "give me the details of
    # grocery spending in April" is not flattened into one number.
    if _LIST_CUES.search(text) and not _SUMMARY_CUES.search(text) \
            and (category or month or _LIST_NOUN_RE.search(text)):
        phrase = None if category else _listing_phrase(text)
        listing_kind = kind or "expense"
        found = analytics.search(db, user, category=category, text=phrase, month=month,
                                 kind=listing_kind, limit=LIST_LIMIT)
        # Search's own totals stay authoritative; the model only re-states them.
        facts = _listing_facts(found, category, phrase, month, listing_kind)
        if not category and not month:
            # "Show my transactions." is a new subject: whatever the thread was
            # comparing must not stay authoritative for the next follow-up.
            resolved["reset"] = True
        return done("list_transactions",
                    {"category": category, "text": phrase, "month": month, "kind": listing_kind},
                    facts)

    try:
        # ── category comparison ────────────────────────────────────────────
        thread_intent = context.get("intent") if isinstance(context, dict) else None
        ctx_category = context.get("category") if isinstance(context, dict) else None
        ctx_month = context.get("month") if isinstance(context, dict) else None
        ctx_pair = context.get("comparison_target") if isinstance(context, dict) else None

        def comparison(left, right, period, trade_kind):
            # Remember the pair, never the totals: they are re-queried every turn.
            resolved.update({"category": left, "month": period, "kind": trade_kind,
                             "comparison_target": right})
            facts = analytics.compare_categories(db, user, left, right, month=period,
                                                 kind=trade_kind or "expense")
            return done("compare_categories",
                        {"categories": [left, right], "month": period, "kind": trade_kind},
                        facts)

        wants_compare = bool(_COMPARE_CUE.search(text)) and not _WRITE_CUE.search(text)
        # "what about June?" keeps the pair; "and my electricity bill?" is an amount
        # question and must not be turned into a comparison.
        asks_amount = bool(_SUMMARY_CUES.search(text) or _DIMENSION_Q.search(text)
                           or _KIND_EXPENSE.search(text))
        sticky_compare = bool(
            thread_intent == "compare_categories" and ctx_pair and not _WRITE_CUE.search(text)
            and (wants_compare or (_SWITCH_CUE.search(message) and not asks_amount))
        )
        if wants_compare:
            terms = _split_comparison(message)
            if terms:
                left_match = analytics.match_categories(db, user, terms[0])
                right_match = analytics.match_categories(db, user, terms[1])
                if left_match and right_match:
                    return comparison(left_match[0], right_match[0], month, kind)
                missing = terms[0] if not left_match else terms[1]
                return done("unknown_category", {"phrase": missing, "month": month},
                            {"status": "unknown_category", "category": missing,
                             "requested_category": missing, "scope": None, "month": month,
                             "known_categories": pool,
                             "message": (f'You have no category called "{missing}" — I cannot '
                                         f'compare it.')})
            if len(mentioned) >= 2:
                return comparison(mentioned[0], mentioned[1], month, kind)
            if sticky_compare:
                return comparison(category or ctx_category, ctx_pair, month or ctx_month, kind)
            if len(_month_names(text)) >= 2 and not mentioned:
                pass          # "compare May and June" — the months comparator below owns it
            elif _PERIOD_COMPARISON.search(text):
                return done("clarify", {"month": month},
                            {"status": "ambiguous", "month": month,
                             "question": ("I can compare two categories in one period, or two "
                                          "months overall — which would you like?")})
            else:
                return done("clarify", {"month": month},
                            {"status": "ambiguous", "month": month,
                             "question": "Which two categories would you like to compare?"})
        elif sticky_compare:
            return comparison(category or ctx_category, ctx_pair, month or ctx_month, kind)

        # "what about June?" after a listing is the same listing, one month on.
        month_switch = bool(
            isinstance(context, dict)
            and thread_intent in ("list_transactions", "merchants", "category_ranking")
            and month and not mentioned
            and _SWITCH_CUE.search(message)
            and not _SUMMARY_CUES.search(text)
            and not _COMPARE_CUE.search(text)
            and not _WRITE_CUE.search(text)
        )
        if month_switch and thread_intent == "category_ranking":
            top = _RANK_LIMIT.search(text)
            rank_limit = int(top.group(1)) if top else 5
            facts = analytics.category_ranking(db, user, month=month, limit=rank_limit,
                                               kind=kind or context.get("kind") or "expense")
            return done("category_ranking",
                        {"month": month, "year": None, "limit": rank_limit}, facts)

        if month_switch and thread_intent == "list_transactions":
            list_kind = kind or context.get("kind") or "expense"
            found = analytics.search(db, user, category=category, month=month,
                                     kind=list_kind, limit=LIST_LIMIT)
            return done("list_transactions",
                        {"category": category, "text": None, "month": month, "kind": list_kind},
                        _listing_facts(found, category, None, month, list_kind))

        # "which merchant contributed most?" is a question about merchants, even
        # when the category and month were inherited — answer the question asked.
        # A correction or a switch on a merchant thread stays a merchant question.
        thread_intent = context.get("intent") if isinstance(context, dict) else None
        # "and my electricity bill?" is an amount question, not a merchant one.
        asks_amount = bool(_SUMMARY_CUES.search(text) or _DIMENSION_Q.search(text)
                           or _KIND_EXPENSE.search(text))
        asks_merchants = bool(
            re.search(r"\bmerchant|where did i spend|who did i pay|most frequent\b", text)
        ) or (thread_intent == "merchants"
              and (_CORRECTION.search(text)
                   or (_SWITCH_CUE.search(message) and not asks_amount)))
        if asks_merchants:
            # The settled category/kind, not the raw message: an inherited or
            # corrected filter must reach the query, and its absence means "all".
            facts = analytics.merchants(db, user, month, category=category,
                                        kind=kind or "expense")
            return done("merchants", {"month": month, "category": category}, facts)

        if category and month:
            return done("category_month", {"category": category, "month": month},
                        analytics.category_month(db, user, category, month))

        if category:
            facts = analytics.category_series(db, user, category)
            return done("category_series", {"category": category}, facts)

        if re.search(r"\bcompare\b|\bversus\b|\bvs\b|\bcompared to\b", text):
            found = re.findall(r"\b(" + "|".join(MONTH_NAMES) + r")\b", text, re.I)
            months = []
            for name in found:
                mon = MONTH_NAMES[name.lower()]
                year = today.year if mon <= today.month else today.year - 1
                months.append(f"{year:04d}-{mon:02d}")
            if len(months) >= 2:
                return done("compare_months", {"months": months[:2]},
                            analytics.compare_months(db, user, months[0], months[1]))

        if re.search(r"\brecurring|subscription|every month|monthly bill\b", text):
            return done("recurring", {}, analytics.recurring(db, user))

        if re.search(r"\blargest|biggest|highest\b.*\btransaction|\bmost expensive\b", text):
            return done("largest_transactions", {"month": month},
                        analytics.highest_transactions(db, user, month=month))

        if _wants_extremes(text) and re.search(r"\bmonth\b", text):
            return done("extremes", {}, analytics.extremes(db, user))

        if month and re.search(r"\bspend|spent|expense|saving|income|earn|budget\b", text):
            return done("month_summary", {"month": month},
                        analytics.summary(db, user, month, today=today))

        months_back = _months_back(message)
        if months_back or re.search(r"\btrend|over time|month by month|history\b", text):
            return done("monthly_series", {"months": months_back},
                        analytics.monthly_series(db, user, months=months_back))

        if re.search(r"\ball time\b|\bever\b|\bsince i started\b", text):
            return done("all_time", {},
                        {"months": analytics.monthly_series(db, user),
                         "extremes": analytics.extremes(db, user)})
    except Exception as exc:  # noqa: BLE001 - analytics must never break a turn
        obs.inc("analytics_error")
        obs.event("analytics_error", error=str(exc)[:200], intent="planner")
        return {**done("analytics_error", {}, None), "error": str(exc)[:200]}

    return done(None, {}, None)


def available_range(db: Session, user) -> dict:
    """First/last month and a row count — one aggregate, no ledger in memory."""
    return analytics.available_range(db, user)
