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

from sqlalchemy.orm import Session

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
    "recent", "every", "each", "of", "and", "down", "me", "give", "show", "list", "display",
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


def _singular(token: str) -> str:
    """A crude, predictable singular: groceries -> grocery, bills -> bill."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


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


def analyse(db: Session, user, message: str, today: date | None = None) -> dict:
    """Return {"intent", "facts"} — facts is None when no query applies."""
    today = today or date.today()
    text = normalise(message)
    month = resolve_month(message, today)
    pool = analytics.categories(db, user)

    # A category only counts when it is one of this user's real categories.
    mentioned = [c for c in pool if normalise(c) and normalise(c) in text]
    if not mentioned:
        # plural/partial forms: "grocery" for Groceries, "office eat" for Office eats
        for candidate in pool:
            tokens = [t for t in normalise(candidate).split() if len(t) >= 4]
            if tokens and all(t in text or _singular(t) in text for t in tokens):
                mentioned.append(candidate)

    # A spend question about something that is not in the ledger at all.
    # Answering it with a figure (even a zero) is a fabrication, so name it.
    if not mentioned and re.search(r"\b(spend|spent|paid|cost)\b", text):
        phrase = _object_of_spending(normalise(message))
        if phrase and len(phrase) <= 40 and not re.search(r"\d", phrase) \
                and not analytics.text_exists(db, user, phrase):
            if not analytics.match_categories(db, user, phrase):
                return {
                    "intent": "unknown_category",
                    "query": {"phrase": phrase, "month": month},
                    "facts": {
                        "status": "unknown_category",
                        "category": phrase,
                        "month": month,
                        "known_categories": pool,
                        "message": (f"You have no category or transaction called \"{phrase}\" — I cannot give a figure for it."),
                    },
                }

    # A listing request is answered with the records, not with a total. It is
    # checked before the category+month aggregate so "give me the details of
    # grocery spending in April" is not flattened into one number.
    if _LIST_CUES.search(text) and not _SUMMARY_CUES.search(text) \
            and (mentioned or month or _LIST_NOUN_RE.search(text)):
        category = mentioned[0] if mentioned else None
        phrase = None if category else _listing_phrase(text)
        kind = "income" if re.search(r"\bincome\b|\bsalary\b|\bearned\b|\breceived\b", text) else "expense"
        found = analytics.search(db, user, category=category, text=phrase, month=month,
                                 kind=kind, limit=LIST_LIMIT)
        rows = found.get("transactions") or []
        # Search's own totals stay authoritative; the model only re-states them.
        facts = {
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
        return {"intent": "list_transactions",
                "query": {"category": category, "text": phrase, "month": month, "kind": kind},
                "facts": facts}

    try:
        if mentioned and month:
            return {"intent": "category_month", "query": {"category": mentioned[0], "month": month},
                    "facts": analytics.category_month(db, user, mentioned[0], month)}

        if mentioned:
            facts = analytics.category_series(db, user, mentioned[0])
            return {"intent": "category_series", "query": {"category": mentioned[0]}, "facts": facts}

        if re.search(r"\bcompare\b|\bversus\b|\bvs\b|\bcompared to\b", text):
            found = re.findall(r"\b(" + "|".join(MONTH_NAMES) + r")\b", text, re.I)
            months = []
            for name in found:
                mon = MONTH_NAMES[name.lower()]
                year = today.year if mon <= today.month else today.year - 1
                months.append(f"{year:04d}-{mon:02d}")
            if len(months) >= 2:
                return {"intent": "compare_months", "query": {"months": months[:2]},
                        "facts": analytics.compare_months(db, user, months[0], months[1])}

        if re.search(r"\bmerchant|where did i spend|who did i pay|most frequent\b", text):
            return {"intent": "merchants", "query": {"month": month},
                    "facts": analytics.merchants(db, user, month)}

        if re.search(r"\brecurring|subscription|every month|monthly bill\b", text):
            return {"intent": "recurring", "query": {}, "facts": analytics.recurring(db, user)}

        if re.search(r"\blargest|biggest|highest\b.*\btransaction|\bmost expensive\b", text):
            return {"intent": "largest_transactions", "query": {"month": month},
                    "facts": analytics.highest_transactions(db, user, month=month)}

        if _wants_extremes(text) and re.search(r"\bmonth\b", text):
            return {"intent": "extremes", "query": {}, "facts": analytics.extremes(db, user)}

        if month and re.search(r"\bspend|spent|expense|saving|income|earn|budget\b", text):
            return {"intent": "month_summary", "query": {"month": month},
                    "facts": analytics.summary(db, user, month, today=today)}

        months_back = _months_back(message)
        if months_back or re.search(r"\btrend|over time|month by month|history\b", text):
            return {"intent": "monthly_series", "query": {"months": months_back},
                    "facts": analytics.monthly_series(db, user, months=months_back)}

        if re.search(r"\ball time\b|\bever\b|\bsince i started\b", text):
            return {"intent": "all_time", "query": {},
                    "facts": {"months": analytics.monthly_series(db, user),
                              "extremes": analytics.extremes(db, user)}}
    except Exception as exc:  # noqa: BLE001 - analytics must never break a turn
        obs.inc("analytics_error")
        obs.event("analytics_error", error=str(exc)[:200], intent="planner")
        return {"intent": "analytics_error", "query": {}, "facts": None, "error": str(exc)[:200]}

    return {"intent": None, "query": {}, "facts": None}


def available_range(db: Session, user) -> dict:
    """First/last month and a row count — one aggregate, no ledger in memory."""
    return analytics.available_range(db, user)
