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

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from .. import models


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
        entry = buckets.setdefault(key, {"income": 0.0, "expense": 0.0, "count": 0})
        entry[name if name in ("income", "expense") else "expense"] += float(total or 0)
        entry["count"] += int(count or 0)
    for entry in buckets.values():
        entry["income"] = round(entry["income"], 2)
        entry["expense"] = round(entry["expense"], 2)
        entry["savings"] = round(entry["income"] - entry["expense"], 2)
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
    found = {name: (float(total or 0), int(count or 0)) for name, total, count in rows}

    # One entry per matched category, in the order the matcher returned them — a
    # category with no rows this month is reported as 0.0/0, never omitted.
    totals = []
    for name in matched:
        total, count = found.get(name.lower(), (0.0, 0))
        totals.append({"category": name, "total": round(total, 2), "count": count})

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
        "total": round(sum(t["total"] for t in totals), 2),
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
        {"month": key, "total": round(float(total or 0), 2), "count": int(count or 0)}
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
        "total": round(sum(s["total"] for s in series), 2),
        "months": len(series),
        "average": round(sum(s["total"] for s in series) / len(series), 2),
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
    totals = {name: float(total or 0) for name, total in rows}
    overall = sum(totals.values()) or 1.0
    values = [
        {"category": k, "total": round(v, 2), "share_pct": round(v / overall * 100, 1)}
        for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return {
        "status": "ok",
        "month": month,
        "total": round(sum(totals.values()), 2),
        "categories": values,
        "highest": values[0],
        "lowest": values[-1],
    }


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
        out["expense_delta"] = round(b["expense"] - a["expense"], 2)
        out["income_delta"] = round(b["income"] - a["income"], 2)
        out["expense_change_pct"] = round((b["expense"] - a["expense"]) / a["expense"] * 100, 1) if a["expense"] else None
    return out


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

def merchants(db: Session, user, month: str | None = None, limit: int = 8) -> dict:
    start = end = None
    if month:
        start, end = month_bounds(month)
    name = func.lower(func.trim(models.Transaction.description))
    rows = (
        _filtered(db, user, start=start, end=end, kind="expense")
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
        return {"status": "no_data", "month": month}
    ranked = [
        {"merchant": label, "total": round(float(total or 0), 2), "count": int(count or 0),
         "_first": int(first_id or 0)}
        for _key, label, total, count, first_id in rows
    ]
    ranked.sort(key=lambda e: (-e["total"], e["_first"]))
    top = ranked[:limit]
    frequent = sorted(ranked, key=lambda e: -e["count"])[:limit]

    # The category shown for a merchant is the one on its oldest transaction in
    # the same window — what the row-by-row loop reported, without trusting the
    # scan order. Only the merchants being returned are looked up.
    wanted = {e["merchant"].strip().lower() for e in top} | {e["merchant"].strip().lower() for e in frequent}
    first_category: dict[str, str] = {}
    if wanted:
        key = func.lower(func.trim(models.Transaction.description))
        for merchant_key, category in (
            _filtered(db, user, start=start, end=end, kind="expense")
            .filter(key.in_(sorted(wanted)))
            .with_entities(key, models.Transaction.category)
            .order_by(models.Transaction.id.asc())
            .all()
        ):
            first_category.setdefault(merchant_key, category)
    for entry in ranked:
        entry["category"] = first_category.get(entry["merchant"].strip().lower())
        entry.pop("_first", None)

    return {"status": "ok", "month": month, "merchants": top, "most_frequent": frequent}


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
         "average": round(float(total or 0) / int(count or 1), 2), "last_month": last_month,
         "_first": int(first_id or 0)}
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
        "total": round(float(total or 0), 2),
        "transactions": [
            {"date": r.txn_date.isoformat(), "kind": r.kind, "amount": round(float(r.amount or 0), 2),
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
        "items": [{"date": r.txn_date.isoformat(), "amount": round(float(r.amount or 0), 2),
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
    income = round(sum(float(total or 0) for name, total, _count in rows if name == "income"), 2)
    expense = round(sum(float(total or 0) for name, total, _count in rows if name == "expense"), 2)
    count = sum(int(c or 0) for _name, _total, c in rows)
    return {
        "status": "ok",
        "month": month,
        "income": income,
        "expense": expense,
        "savings": round(income - expense, 2),
        "savings_rate": round((income - expense) / income * 100, 1) if income else None,
        "count": count,
    }
