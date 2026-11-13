"""Deterministic financial analytics.

The assistant never adds numbers up. Every figure it states comes from one of
these functions, which run against Postgres and return a status the model can
tell apart:

    ok                  → the query ran; `total` may legitimately be 0.0
    unknown_category    → this user has never used that category
    no_data             → no transactions at all in the requested range
    no_data_for_category→ the category exists but not in that range

`ok` with 0.0 means "you really spent nothing". Anything else means "I could
not see that range", and the reply must say so instead of quoting ₹0.

Aggregation happens in the database. Nothing here loads a user's ledger in order
to sum it: only the row-level answers (a search page, the top few transactions)
fetch rows, and those are bounded by the limit the caller asked for.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from .. import models, money


# ── range helpers ────────────────────────────────────────────────────────────

def month_bounds(month: str) -> tuple[date, date]:
    year, mon = (int(x) for x in month.split("-"))
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


def shift_month(month: str, delta: int) -> str:
    year, mon = (int(x) for x in month.split("-"))
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def current_month(today: date | None = None) -> str:
    """The month in the caller's calendar; UTC when no context is supplied."""
    return (today or date.today()).strftime("%Y-%m")


# ── SQL building blocks ──────────────────────────────────────────────────────
# The rules the previous Python loops enforced, expressed once: income is
# kind='income', every other kind counts as expense, a month key is 'YYYY-MM',
# and money is rounded to paise only after it has been summed.

def month_expr(db: Session):
    """'YYYY-MM' for txn_date, in whatever dialect this session is bound to."""
    txn_date = models.Transaction.txn_date
    if db.get_bind().dialect.name == "sqlite":
        return func.strftime("%Y-%m", txn_date)
    return func.to_char(txn_date, "YYYY-MM")


def kind_bucket_expr():
    """income stays income; anything else was bucketed as expense."""
    return case((models.Transaction.kind == "income", "income"), else_="expense")


def _like_pattern(probe: str) -> str:
    """A contains-pattern with LIKE metacharacters escaped, for a literal match."""
    escaped = probe.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filtered(db: Session, user, *, start: date | None = None, end: date | None = None,
              kind: str | None = None, categories: list[str] | None = None):
    """The one WHERE clause every aggregate shares, so user isolation cannot drift."""
    query = db.query(models.Transaction).filter(models.Transaction.user_id == user.id)
    if start is not None:
        query = query.filter(models.Transaction.txn_date >= start)
    if end is not None:
        query = query.filter(models.Transaction.txn_date <= end)
    if kind:
        query = query.filter(models.Transaction.kind == kind)
    if categories:
        query = query.filter(
            func.lower(models.Transaction.category).in_([c.lower() for c in categories])
        )
    return query


def categories(db: Session, user) -> list[str]:
    rows = (
        db.query(models.Transaction.category)
        .filter(models.Transaction.user_id == user.id)
        .distinct()
        .all()
    )
    return sorted({str(r[0]) for r in rows if r[0]})


def match_categories(db: Session, user, wanted: str) -> list[str]:
    """Resolve a spoken category name to the user's real ones."""
    from .resolve import normalise

    probe = normalise(wanted)
    if not probe:
        return []
    pool = categories(db, user)
    exact = [c for c in pool if normalise(c) == probe]
    if exact:
        return exact
    partial = [c for c in pool if probe in normalise(c) or normalise(c) in probe]
    if partial:
        return partial
    words = set(probe.split())
    scored = [(len(words & set(normalise(c).split())), c) for c in pool]
    best = max((s for s, _ in scored), default=0)
    return [c for s, c in scored if s == best and s > 0]


def text_exists(db: Session, user, phrase: str) -> bool:
    """Does this phrase appear anywhere in the user's categories or descriptions?"""
    probe = (phrase or "").strip().lower()
    if not probe:
        return False
    pattern = _like_pattern(probe)
    hit = (
        db.query(models.Transaction.id)
        .filter(models.Transaction.user_id == user.id)
        .filter(or_(
            func.lower(func.coalesce(models.Transaction.category, "")).like(pattern, escape="\\"),
            func.lower(func.coalesce(models.Transaction.description, "")).like(pattern, escape="\\"),
        ))
        .limit(1)
        .first()
    )
    return hit is not None


def _month_buckets(db: Session, user, *, start: date | None = None, end: date | None = None,
                   categories_in: list[str] | None = None, kind: str | None = None) -> dict[str, dict]:
    """Income/expense/count per month, summed in SQL and rounded here."""
    month = month_expr(db)
    bucket = kind_bucket_expr()
    rows = (
        _filtered(db, user, start=start, end=end, kind=kind, categories=categories_in)
        .with_entities(
            month.label("month"),
            bucket.label("bucket"),
            func.sum(models.Transaction.amount),
            func.count(models.Transaction.id),
        )
        .group_by(month, bucket)
        .all()
    )
    buckets: dict[str, dict] = {}
    for key, name, total, count in rows:
        if not key:
            continue
        entry = buckets.setdefault(key, {"income": money.ZERO, "expense": money.ZERO, "count": 0})
        entry[name if name in ("income", "expense") else "expense"] += money.to_money(total, default=money.ZERO)
        entry["count"] += int(count or 0)
    for entry in buckets.values():
        income = money.to_money(entry["income"], default=money.ZERO)
        expense = money.to_money(entry["expense"], default=money.ZERO)
        entry["income"] = money.number(income)
        entry["expense"] = money.number(expense)
        entry["savings"] = money.number(income - expense)
    return dict(sorted(buckets.items()))


# ── category analytics ───────────────────────────────────────────────────────

def category_month(db: Session, user, category: str, month: str) -> dict:
    matched = match_categories(db, user, category)
    if not matched:
        return {
            "status": "unknown_category",
            "category": category,
            "month": month,
            "known_categories": categories(db, user),
            "message": f"You have never used a category called \"{category}\".",
        }
    start, end = month_bounds(month)
    key = func.lower(models.Transaction.category)
    rows = (
        _filtered(db, user, start=start, end=end, kind="expense", categories=matched)
        .with_entities(key, func.sum(models.Transaction.amount), func.count(models.Transaction.id))
        .group_by(key)
        .all()
    )
    found = {name: (money.to_money(total, default=money.ZERO), int(count or 0)) for name, total, count in rows}

    # One entry per matched category, in the order the matcher returned them — a
    # category with no rows this month is reported as 0.0/0, never omitted.
    totals = []
    for name in matched:
        total, count = found.get(name.lower(), (money.ZERO, 0))
        totals.append({"category": name, "total": money.number(total), "count": count})

    month_key = month_expr(db)
    months_with = sorted({
        row[0] for row in (
            _filtered(db, user, categories=matched)
            .with_entities(month_key)
            .distinct()
            .all()
        )
        if row[0]
    })

    any_rows = sum(t["count"] for t in totals)
    return {
        "status": "ok" if any_rows else "no_data_for_category",
        "month": month,
        "categories": matched,
        "months_with_category": months_with,
        "total": money.number(money.total(t["total"] for t in totals)),
        "count": any_rows,
        "breakdown": totals,
    }


def category_series(db: Session, user, category: str) -> dict:
    matched = match_categories(db, user, category)
    if not matched:
        return {"status": "unknown_category", "category": category,
                "known_categories": categories(db, user)}
    month = month_expr(db)
    rows = (
        _filtered(db, user, kind="expense", categories=matched)
        .with_entities(
            month.label("month"),
            func.sum(models.Transaction.amount),
            func.count(models.Transaction.id),
        )
        .group_by(month)
        .all()
    )
    if not rows:
        return {"status": "no_data_for_category", "category": category, "categories": matched}
    series = [
        {"month": key, "total": money.number(money.to_money(total, default=money.ZERO)),
         "count": int(count or 0)}
        for key, total, count in sorted(rows)
        if key
    ]
    peak = max(series, key=lambda s: s["total"])
    low = min(series, key=lambda s: s["total"])
    return {
        "status": "ok",
        "category": matched[0],
        "categories": matched,
        "series": series,
        "total": money.number(money.total(s["total"] for s in series)),
        "months": len(series),
        "average": money.number(money.total(s["total"] for s in series) / len(series)),
        "max_month": peak,
        "min_month": low,
    }


def category_by_month(db: Session, user, month: str) -> dict:
    start, end = month_bounds(month)
    # The `row.category or "Other"` the loop used to apply.
    label = case(
        (models.Transaction.category.is_(None), "Other"),
        (models.Transaction.category == "", "Other"),
        else_=models.Transaction.category,
    )
    rows = (
        _filtered(db, user, start=start, end=end, kind="expense")
        .with_entities(label, func.sum(models.Transaction.amount))
        .group_by(label)
        .all()
    )
    if not rows:
        return {"status": "no_data", "month": month}
    totals = {name: money.to_money(total, default=money.ZERO) for name, total in rows}
    overall = money.total(totals.values()) or money.CENT
    values = [
        {"category": k, "total": money.number(v), "share_pct": round(float(v / overall * 100), 1)}
        for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return {
        "status": "ok",
        "month": month,
        "total": money.number(money.total(totals.values())),
        "categories": values,
        "highest": values[0],
        "lowest": values[-1],
    }


# ── category ranking ─────────────────────────────────────────────────────────

def category_ranking(db: Session, user, *, month: str | None = None, year: int | None = None,
                     limit: int = 5, kind: str = "expense") -> dict:
    """Which categories took the most money in one window — ranked in SQL.

    One GROUP BY returns at most `limit` rows, so the answer never depends on
    loading a ledger. Case variants of one category are one rank; a missing
    category is "Other", as everywhere else. `no_data` means the window is
    empty, never that the user spent nothing.
    """
    start = end = None
    scope = "all time"
    if month:
        start, end = month_bounds(month)
        scope = month
    elif year is not None:
        start, end = date(int(year), 1, 1), date(int(year), 12, 31)
        scope = f"{int(year):04d}"
    limit = 5 if limit is None else max(1, min(int(limit), 20))

    label = case(
        (models.Transaction.category.is_(None), "Other"),
        (models.Transaction.category == "", "Other"),
        else_=models.Transaction.category,
    )
    key = func.lower(label)          # "groceries" and "Groceries" are one rank
    name = func.min(label)           # ... reported under a real spelling
    amount = func.sum(models.Transaction.amount)
    count = func.count(models.Transaction.id)

    overall, rows_total = (
        _filtered(db, user, start=start, end=end, kind=kind)
        .with_entities(amount, count)
        .one()
    )
    total = money.to_money(overall, default=money.ZERO)
    if not int(rows_total or 0):
        return {"status": "no_data", "scope": scope, "month": month, "year": year,
                "kind": kind, "limit": limit, "total": 0.0, "count": 0, "categories": [],
                "top": None, "ranked": 0}

    rows = (
        _filtered(db, user, start=start, end=end, kind=kind)
        .with_entities(name, amount, count)
        .group_by(key)
        .order_by(amount.desc(), name)
        .limit(limit)
        .all()
    )
    ranked = []
    for category, subtotal, subtotal_count in rows:
        value = money.to_money(subtotal, default=money.ZERO)
        ranked.append({
            "category": category,
            "total": money.number(value),
            "count": int(subtotal_count or 0),
            # Share of the window's total, not of the shown top-N.
            "share_pct": round(float(value / total * 100), 1) if total else None,
        })
    return {
        "status": "ok",
        "scope": scope,
        "month": month,
        "year": year,
        "kind": kind,
        "limit": limit,
        "total": money.number(total),
        "count": int(rows_total or 0),
        "categories": ranked,
        "top": ranked[0] if ranked else None,
        "ranked": len(ranked),
    }


# ── unusual expenses ─────────────────────────────────────────────────────────

# A month or two of a category is not a distribution: with fewer than this many
# earlier expenses, "unusual" would be a guess, so the function says so instead.
MIN_HISTORY = 5
# Iglewicz & Hoaglin's cut-off for the modified z-score (0.6745·|x−median|/MAD).
OUTLIER_Z = Decimal("3.5")
# MAD is the median of absolute deviations, so it rescales to a sigma-like unit.
MAD_TO_SIGMA = Decimal("1.4826")
CANDIDATE_LIMIT = 50
BASELINE_LIMIT = 5000


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _baseline(amounts: list[Decimal]) -> tuple[Decimal, Decimal]:
    median = _median(amounts)
    return median, _median([abs(value - median) for value in amounts])


def _judge(amount: Decimal, history: list[Decimal]) -> dict | None:
    """How far one expense sits from its category's own history, or None if thin.

    Modified z-score against median absolute deviation: robust to the very
    outliers it is looking for, and it needs no assumption about the shape of
    the distribution. When more than half a category's amounts are identical the
    MAD is 0, so the fallback is a median multiple — still deterministic.
    """
    if len(history) < MIN_HISTORY:
        return None
    median, mad = _baseline(history)
    difference = amount - median
    if median > 0:
        ratio = (amount / median).quantize(Decimal("0.01"))
    else:
        ratio = None
    if mad > 0:
        sigma = mad * MAD_TO_SIGMA
        z = ((amount - median) / sigma).quantize(Decimal("0.01"))
        unusual = z >= OUTLIER_Z
        rule = "modified_z"
    else:
        sigma = z = None
        unusual = amount >= median * 2 and difference > 0
        rule = "median_multiple"
    return {
        "median": median, "mad": mad, "sigma": sigma, "z": z, "ratio": ratio,
        "difference": difference, "history_count": len(history),
        "unusual": bool(unusual and difference > 0), "rule": rule,
    }


def unusual_expenses(db: Session, user, *, month: str | None = None, year: int | None = None,
                     category: str | None = None, limit: int = 5, recent: bool = False,
                     probe_amount: Decimal | None = None) -> dict:
    """Individual expenses far above their own category's history.

    Every candidate is compared with the category's other expenses — never with
    the candidate itself, never with income — and only a *higher* amount can be
    flagged. Nothing is inferred from a category with too little history.
    """
    start = end = None
    scope = "all time"
    if month:
        start, end = month_bounds(month)
        scope = month
    elif year is not None:
        start, end = date(int(year), 1, 1), date(int(year), 12, 31)
        scope = f"{int(year):04d}"
    limit = 5 if limit is None else max(1, min(int(limit), 20))

    matched: list[str] = []
    if category:
        matched = match_categories(db, user, category)
        if not matched:
            return {"status": "unknown_category", "category": category, "scope": scope,
                    "known_categories": categories(db, user),
                    "message": f'You have no category called "{category}".'}

    def history_for(label: str | None, exclude_id):
        key = (label or "").lower()
        query = _filtered(db, user, kind="expense")
        if label is None or label == "":
            query = query.filter(or_(models.Transaction.category.is_(None),
                                     models.Transaction.category == ""))
        else:
            query = query.filter(func.lower(models.Transaction.category) == key)
        if exclude_id is not None:
            query = query.filter(models.Transaction.id != exclude_id)
        return [money.to_money(value, default=money.ZERO)
                for (value,) in query.with_entities(models.Transaction.amount)
                .limit(BASELINE_LIMIT).all()]

    # The window holds only expenses (income is never a candidate).
    window = _filtered(db, user, start=start, end=end, kind="expense")
    if matched:
        window = window.filter(func.lower(models.Transaction.category).in_(
            [name.lower() for name in matched]))
    if recent:
        candidates = (window.order_by(models.Transaction.txn_date.desc(),
                                      models.Transaction.id.desc())
                      .limit(max(limit, 5)).all())
    else:
        candidates = (window.order_by(models.Transaction.amount.desc(),
                                      models.Transaction.id.asc())
                      .limit(CANDIDATE_LIMIT).all())
    if not candidates:
        return {"status": "no_data", "scope": scope, "month": month, "year": year,
                "category": matched[0] if matched else None, "limit": limit,
                "candidates": 0, "evaluated": 0, "count": 0, "anomalies": [],
                "categories_needing_history": []}

    anomalies, thin, evaluated = [], set(), 0
    for row in candidates:
        history = history_for(row.category, row.id)
        verdict = _judge(money.to_money(row.amount, default=money.ZERO), history)
        if verdict is None:
            thin.add(row.category or "Other")
            continue
        evaluated += 1
        if not verdict["unusual"]:
            continue
        anomalies.append({
            "id": row.id,
            "date": row.txn_date.isoformat(),
            "description": row.description,
            "category": row.category or "Other",
            "amount": money.number(row.amount),
            "median": money.number(verdict["median"]),
            "mad": money.number(verdict["mad"]),
            "difference": money.number(verdict["difference"]),
            "ratio": float(verdict["ratio"]) if verdict["ratio"] is not None else None,
            "z": float(verdict["z"]) if verdict["z"] is not None else None,
            "history_count": verdict["history_count"],
            "rule": verdict["rule"],
        })

    anomalies.sort(key=lambda a: (a["z"] if a["z"] is not None else a["ratio"] or 0), reverse=True)
    facts = {
        "status": "ok" if evaluated else "insufficient_history",
        "scope": scope,
        "month": month,
        "year": year,
        "category": matched[0] if matched else None,
        "method": "median + MAD (modified z-score)",
        "threshold": float(OUTLIER_Z),
        "min_history": MIN_HISTORY,
        "limit": limit,
        "candidates": len(candidates),
        "evaluated": evaluated,
        "count": min(len(anomalies), limit),
        "anomalies": anomalies[:limit],
        "categories_needing_history": sorted(thin),
    }

    if probe_amount is not None:
        label = matched[0] if matched else (candidates[0].category or "Other")
        history = history_for(label, None)
        verdict = _judge(money.to_money(probe_amount, default=money.ZERO), history)
        facts["probe"] = None if verdict is None else {
            "amount": money.number(probe_amount),
            "category": label,
            "median": money.number(verdict["median"]),
            "difference": money.number(verdict["difference"]),
            "ratio": float(verdict["ratio"]) if verdict["ratio"] is not None else None,
            "z": float(verdict["z"]) if verdict["z"] is not None else None,
            "history_count": verdict["history_count"],
            "unusual": verdict["unusual"],
            "rule": verdict["rule"],
        }
    return facts


# ── monthly analytics ────────────────────────────────────────────────────────

def monthly_series(db: Session, user, months: int | None = None, year: int | None = None) -> dict:
    buckets = _month_buckets(db, user)
    if not buckets:
        return {"status": "no_data"}
    keys = list(buckets)
    if year is not None:
        keys = [k for k in keys if k.startswith(f"{year:04d}-")]
    if months:
        keys = keys[-months:]
    selected = {k: buckets[k] for k in keys}
    if not selected:
        return {"status": "no_data", "requested_months": months, "requested_year": year}
    return {
        "status": "ok",
        "months": [
            {"month": k, **v, "savings_rate": round(v["savings"] / v["income"] * 100, 1) if v["income"] else None}
            for k, v in selected.items()
        ],
        "available_range": {"first": min(buckets), "last": max(buckets)},
    }


def extremes(db: Session, user) -> dict:
    buckets = _month_buckets(db, user)
    if not buckets:
        return {"status": "no_data"}
    expense = {k: v["expense"] for k, v in buckets.items() if v["expense"] > 0}
    income = {k: v["income"] for k, v in buckets.items() if v["income"] > 0}
    return {
        "status": "ok",
        "highest_expense_month": {"month": max(expense, key=expense.get), "total": max(expense.values())} if expense else None,
        "lowest_expense_month": {"month": min(expense, key=expense.get), "total": min(expense.values())} if expense else None,
        "highest_income_month": {"month": max(income, key=income.get), "total": max(income.values())} if income else None,
        "range": {"first": min(buckets), "last": max(buckets)},
    }


def compare_months(db: Session, user, month_a: str, month_b: str) -> dict:
    series = monthly_series(db, user)
    if series.get("status") != "ok":
        return series
    lookup = {m["month"]: m for m in series["months"]}
    a, b = lookup.get(month_a), lookup.get(month_b)
    if not a and not b:
        return {"status": "no_data", "months": [month_a, month_b],
                "available_range": series["available_range"]}
    out = {"status": "ok", "a": a, "b": b}
    if a and b:
        out["expense_delta"] = money.number(money.to_money(b["expense"]) - money.to_money(a["expense"]))
        out["income_delta"] = money.number(money.to_money(b["income"]) - money.to_money(a["income"]))
        out["expense_change_pct"] = round((b["expense"] - a["expense"]) / a["expense"] * 100, 1) if a["expense"] else None
    return out


def compare_categories(db: Session, user, first: str, second: str, month: str | None = None,
                       kind: str = "expense") -> dict:
    """Two categories over one window, aggregated in SQL and compared in Decimal."""
    start = end = None
    if month:
        start, end = month_bounds(month)

    named: list[tuple[str, list[str]]] = []
    for label, wanted in (("first", first), ("second", second)):
        matched = match_categories(db, user, wanted)
        if not matched:
            return {
                "status": "unknown_category",
                "which": label,
                "category": wanted,
                "requested_category": wanted,
                "month": month,
                "scope": None,
                "known_categories": categories(db, user),
                "message": f'You have never used a category called "{wanted}".',
            }
        named.append((wanted, matched))

    # An empty window is missing data, not a pair of zeros.
    if _filtered(db, user, start=start, end=end, kind=kind or None).first() is None:
        return {"status": "no_data", "month": month, "kind": kind}

    key = func.lower(models.Transaction.category)
    wanted_names = [name for _, matched in named for name in matched]
    rows = (
        _filtered(db, user, start=start, end=end, kind=kind or None, categories=wanted_names)
        .with_entities(key, func.sum(models.Transaction.amount), func.count(models.Transaction.id))
        .group_by(key)
        .all()
    )
    found = {name.lower(): (money.to_money(total, default=money.ZERO), int(count or 0))
             for name, total, count in rows}

    sides: list[dict] = []
    amounts: list[Decimal] = []
    for _wanted, matched in named:
        entries = [found[m.lower()] for m in matched if m.lower() in found]
        amount = money.total(entry[0] for entry in entries) if entries else money.ZERO
        amounts.append(amount)
        sides.append({
            "category": matched[0] if len(matched) == 1 else ", ".join(matched),
            "total": money.number(amount),
            "count": sum(entry[1] for entry in entries),
        })

    difference = abs(amounts[0] - amounts[1])
    higher = None
    if amounts[0] > amounts[1]:
        higher = sides[0]["category"]
    elif amounts[1] > amounts[0]:
        higher = sides[1]["category"]

    return {
        "status": "ok",
        "month": month,
        "kind": kind,
        "categories": sides,
        "difference": money.number(difference),
        "higher": higher,
        "equal": amounts[0] == amounts[1],
    }


def available_range(db: Session, user) -> dict:
    """First/last month, month count and transaction count — one aggregate."""
    month = month_expr(db)
    first, last, total, months = (
        db.query(
            func.min(models.Transaction.txn_date),
            func.max(models.Transaction.txn_date),
            func.count(models.Transaction.id),
            func.count(func.distinct(month)),
        )
        .filter(models.Transaction.user_id == user.id)
        .one()
    )
    if not total:
        return {"status": "no_data"}
    return {
        "status": "ok",
        "first_month": first.strftime("%Y-%m"),
        "last_month": last.strftime("%Y-%m"),
        "months": int(months or 0),
        "transactions": int(total),
    }


# ── transaction analytics ────────────────────────────────────────────────────

def merchants(db: Session, user, month: str | None = None, limit: int = 8, *,
              category: str | None = None, kind: str = "expense") -> dict:
    """Top merchants for a window, optionally restricted to one category.

    ``category`` is resolved against the user's real categories with the same
    matcher the rest of the module uses; the filter runs in SQL, so the rows
    never leave the database. ``kind`` defaults to expense, matching the
    original behaviour; pass None for both sides of the ledger.
    """
    start = end = None
    if month:
        start, end = month_bounds(month)
    matched: list[str] = []
    if category:
        matched = match_categories(db, user, category)
        if not matched:
            return {
                "status": "unknown_category",
                "month": month,
                "category": category,
                "requested_category": category,
                "scope": None,
                "known_categories": categories(db, user),
                "message": f'You have never used a category called "{category}".',
            }
    scope = ", ".join(matched) if matched else "all categories"
    matched_label = ", ".join(matched) if matched else None
    name = func.lower(func.trim(models.Transaction.description))
    rows = (
        _filtered(db, user, start=start, end=end, kind=kind or None, categories=matched or None)
        .filter(func.trim(models.Transaction.description) != "")
        .with_entities(
            name.label("merchant_key"),
            func.min(func.trim(models.Transaction.description)).label("label"),
            func.sum(models.Transaction.amount).label("total"),
            func.count(models.Transaction.id).label("count"),
            func.min(models.Transaction.id).label("first_id"),
        )
        .group_by(name)
        .order_by(func.sum(models.Transaction.amount).desc())
        .all()
    )
    if not rows:
        return {"status": "no_data", "month": month, "category": matched_label, "scope": scope}
    ranked = [
        {"merchant": label, "total": money.number(money.to_money(total, default=money.ZERO)),
         "count": int(count or 0), "_first": int(first_id or 0)}
        for _key, label, total, count, first_id in rows
    ]
    ranked.sort(key=lambda e: (-e["total"], e["_first"]))
    top = ranked[:limit]
    frequent = sorted(ranked, key=lambda e: -e["count"])[:limit]

    if matched:
        # Filtered to a category, so that category is the merchant's category here.
        for entry in ranked:
            entry["category"] = matched_label
    else:
        # An all-category total spans categories, so one label would misrepresent
        # it. Group in SQL (merchants x categories, never rows) and list them.
        wanted = ({e["merchant"].strip().lower() for e in top}
                  | {e["merchant"].strip().lower() for e in frequent})
        per_merchant: dict[str, list[tuple[str, float]]] = {}
        if wanted:
            key = func.lower(func.trim(models.Transaction.description))
            for merchant_key, row_category, subtotal in (
                _filtered(db, user, start=start, end=end, kind=kind or None)
                .filter(key.in_(sorted(wanted)))
                .with_entities(key, models.Transaction.category,
                               func.sum(models.Transaction.amount))
                .group_by(key, models.Transaction.category)
                .all()
            ):
                per_merchant.setdefault(merchant_key, []).append(
                    (row_category or "", float(subtotal or 0)))
        for entry in ranked:
            pairs = sorted(per_merchant.get(entry["merchant"].strip().lower(), []),
                           key=lambda pair: (-pair[1], pair[0]))
            entry["categories"] = [name for name, _ in pairs if name]
    for entry in ranked:
        entry.pop("_first", None)

    return {"status": "ok", "month": month, "category": matched_label, "scope": scope,
            "merchants": top, "most_frequent": frequent}


def recurring(db: Session, user, min_months: int = 3) -> dict:
    name = func.lower(func.trim(models.Transaction.description))
    month = month_expr(db)
    rows = (
        _filtered(db, user, kind="expense")
        .filter(func.trim(models.Transaction.description) != "")
        .with_entities(
            name.label("merchant_key"),
            func.min(func.trim(models.Transaction.description)).label("label"),
            func.count(func.distinct(month)).label("months_seen"),
            func.sum(models.Transaction.amount).label("total"),
            func.count(models.Transaction.id).label("count"),
            func.max(month).label("last_month"),
            func.min(models.Transaction.id).label("first_id"),
        )
        .group_by(name)
        .all()
    )
    if not rows:
        return {"status": "no_data"}
    out = [
        {"merchant": label, "months_seen": int(months_seen),
         "average": money.number(money.to_money(total, default=money.ZERO) / int(count or 1)),
         "last_month": last_month, "_first": int(first_id or 0)}
        for _key, label, months_seen, total, count, last_month, first_id in rows
        if int(months_seen or 0) >= min_months
    ]
    # Ties break on the merchant's first transaction, the order the row-by-row
    # loop encountered them in — deterministic instead of scan-order dependent.
    out.sort(key=lambda e: (-e["months_seen"], e["_first"]))
    for entry in out:
        entry.pop("_first", None)
    return {"status": "ok", "recurring": out[:10]} if out else {
        "status": "ok", "recurring": [], "note": f"No merchant repeats in {min_months}+ months."}


def search(db: Session, user, *, text: str | None = None, category: str | None = None,
           month: str | None = None, start: date | None = None, end: date | None = None,
           kind: str | None = None, payment_method: str | None = None, limit: int = 20) -> dict:
    if month:
        start, end = month_bounds(month)
    matched = match_categories(db, user, category) if category else []
    query = _filtered(db, user, start=start, end=end, kind=kind)
    # Mirrors the old filter exactly: one match narrows to that category, several
    # narrow to the set, none filters nothing at all.
    if len(matched) == 1:
        query = query.filter(func.lower(models.Transaction.category) == matched[0].lower())
    elif len(matched) > 1:
        query = query.filter(models.Transaction.category.in_(matched))
    if text:
        probe = _like_pattern(text.strip().lower())
        query = query.filter(
            func.lower(func.coalesce(models.Transaction.description, "")).like(probe, escape="\\")
        )
    if payment_method:
        query = query.filter(
            func.lower(func.coalesce(models.Transaction.payment_method, "")) == payment_method.strip().lower()
        )

    count, total = query.with_entities(
        func.count(models.Transaction.id),
        func.coalesce(func.sum(models.Transaction.amount), 0),
    ).one()
    rows = (
        query.order_by(models.Transaction.txn_date.desc(), models.Transaction.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "status": "ok" if count else ("no_data" if not month and not category and not text else "no_data_for_category"),
        "count": int(count or 0),
        "total": money.number(money.to_money(total, default=money.ZERO)),
        "transactions": [
            {"date": r.txn_date.isoformat(), "kind": r.kind, "amount": money.number(r.amount),
             "category": r.category, "description": r.description, "paid_with": r.payment_method}
            for r in rows
        ],
        "filters": {"text": text, "category": category, "month": month, "kind": kind,
                    "payment_method": payment_method},
    }


def highest_transactions(db: Session, user, kind: str = "expense", month: str | None = None, limit: int = 3) -> dict:
    start = end = None
    if month:
        start, end = month_bounds(month)
    query = _filtered(db, user, start=start, end=end, kind=kind)
    rows = (
        query.order_by(models.Transaction.amount.desc(), models.Transaction.id.asc())
        .limit(limit)
        .all()
    )
    if not rows:
        return {"status": "no_data", "month": month}
    return {
        "status": "ok",
        "items": [{"date": r.txn_date.isoformat(), "amount": money.number(r.amount),
                   "category": r.category, "description": r.description} for r in rows],
    }


def summary(db: Session, user, month: str | None = None, today: date | None = None) -> dict:
    month = month or current_month(today)
    start, end = month_bounds(month)
    rows = (
        _filtered(db, user, start=start, end=end)
        .with_entities(models.Transaction.kind, func.sum(models.Transaction.amount),
                       func.count(models.Transaction.id))
        .group_by(models.Transaction.kind)
        .all()
    )
    income = money.total(total for name, total, _count in rows if name == "income")
    expense = money.total(total for name, total, _count in rows if name == "expense")
    count = sum(int(c or 0) for _name, _total, c in rows)
    return {
        "status": "ok",
        "month": month,
        "income": money.number(income),
        "expense": money.number(expense),
        "savings": money.number(income - expense),
        "savings_rate": round(float((income - expense) / income * 100), 1) if income else None,
        "count": count,
    }
