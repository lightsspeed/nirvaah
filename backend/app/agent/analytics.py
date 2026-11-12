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
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import func
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


def current_month() -> str:
    return date.today().strftime("%Y-%m")


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
    rows = db.query(models.Transaction).filter(models.Transaction.user_id == user.id).all()
    return any(probe in (r.category or "").lower() or probe in (r.description or "").lower()
               for r in rows)


def _rows(db: Session, user, start: date | None = None, end: date | None = None,
          kind: str | None = None, category: str | None = None):
    query = db.query(models.Transaction).filter(models.Transaction.user_id == user.id)
    if start is not None:
        query = query.filter(models.Transaction.txn_date >= start)
    if end is not None:
        query = query.filter(models.Transaction.txn_date <= end)
    if kind:
        query = query.filter(models.Transaction.kind == kind)
    if category:
        query = query.filter(func.lower(models.Transaction.category) == category.lower())
    return query.all()


def _total(rows) -> float:
    return round(sum(float(r.amount or 0) for r in rows), 2)


def _by_month(rows) -> dict[str, dict]:
    buckets: dict[str, dict] = {}
    for row in rows:
        if not row.txn_date:
            continue
        key = row.txn_date.strftime("%Y-%m")
        bucket = buckets.setdefault(key, {"income": 0.0, "expense": 0.0, "count": 0})
        bucket[row.kind if row.kind in ("income", "expense") else "expense"] += float(row.amount or 0)
        bucket["count"] += 1
    for bucket in buckets.values():
        bucket["income"] = round(bucket["income"], 2)
        bucket["expense"] = round(bucket["expense"], 2)
        bucket["savings"] = round(bucket["income"] - bucket["expense"], 2)
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
    totals = []
    for name in matched:
        rows = _rows(db, user, start, end, kind="expense", category=name)
        totals.append({"category": name, "total": _total(rows), "count": len(rows)})
    if not totals:
        return {"status": "no_data_for_category", "category": category, "month": month}
    any_rows = sum(t["count"] for t in totals)
    return {
        "status": "ok" if any_rows else "no_data_for_category",
        "month": month,
        "categories": matched,
        "months_with_category": sorted({r.txn_date.strftime("%Y-%m")
                                        for name in matched
                                        for r in _rows(db, user, category=name) if r.txn_date}),
        "total": round(sum(t["total"] for t in totals), 2),
        "count": any_rows,
        "breakdown": totals,
    }


def category_series(db: Session, user, category: str) -> dict:
    matched = match_categories(db, user, category)
    if not matched:
        return {"status": "unknown_category", "category": category,
                "known_categories": categories(db, user)}
    rows = [r for name in matched for r in _rows(db, user, kind="expense", category=name)]
    if not rows:
        return {"status": "no_data_for_category", "category": category, "categories": matched}
    buckets = _by_month(rows)
    series = [{"month": m, "total": b["expense"], "count": b["count"]} for m, b in buckets.items()]
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
    rows = _rows(db, user, start, end, kind="expense")
    if not rows:
        return {"status": "no_data", "month": month}
    totals: dict[str, float] = {}
    for row in rows:
        totals[row.category or "Other"] = totals.get(row.category or "Other", 0.0) + float(row.amount or 0)
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
    rows = _rows(db, user)
    if not rows:
        return {"status": "no_data"}
    buckets = _by_month(rows)
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
    rows = _rows(db, user)
    if not rows:
        return {"status": "no_data"}
    buckets = _by_month(rows)
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


# ── transaction analytics ────────────────────────────────────────────────────

def merchants(db: Session, user, month: str | None = None, limit: int = 8) -> dict:
    start = end = None
    if month:
        start, end = month_bounds(month)
    rows = [r for r in _rows(db, user, start, end, kind="expense") if (r.description or "").strip()]
    if not rows:
        return {"status": "no_data", "month": month}
    totals: dict[str, dict] = {}
    for row in rows:
        key = row.description.strip().lower()
        entry = totals.setdefault(key, {"merchant": row.description.strip(), "total": 0.0, "count": 0,
                                        "category": row.category})
        entry["total"] += float(row.amount or 0)
        entry["count"] += 1
    ranked = sorted(totals.values(), key=lambda e: e["total"], reverse=True)
    for entry in ranked:
        entry["total"] = round(entry["total"], 2)
    return {"status": "ok", "month": month, "merchants": ranked[:limit],
            "most_frequent": sorted(ranked, key=lambda e: e["count"], reverse=True)[:limit]}


def recurring(db: Session, user, min_months: int = 3) -> dict:
    rows = _rows(db, user, kind="expense")
    if not rows:
        return {"status": "no_data"}
    seen: dict[str, dict] = {}
    for row in rows:
        name = (row.description or "").strip().lower()
        if not name:
            continue
        entry = seen.setdefault(name, {"merchant": row.description.strip(), "months": {}, "amounts": []})
        if row.txn_date:
            entry["months"][row.txn_date.strftime("%Y-%m")] = True
        entry["amounts"].append(float(row.amount or 0))
    out = []
    for entry in seen.values():
        if len(entry["months"]) >= min_months:
            amounts = entry["amounts"]
            out.append({
                "merchant": entry["merchant"],
                "months_seen": len(entry["months"]),
                "average": round(sum(amounts) / len(amounts), 2),
                "last_month": max(entry["months"]),
            })
    out.sort(key=lambda e: e["months_seen"], reverse=True)
    return {"status": "ok", "recurring": out[:10]} if out else {
        "status": "ok", "recurring": [], "note": f"No merchant repeats in {min_months}+ months."}


def search(db: Session, user, *, text: str | None = None, category: str | None = None,
           month: str | None = None, start: date | None = None, end: date | None = None,
           kind: str | None = None, payment_method: str | None = None, limit: int = 20) -> dict:
    if month:
        start, end = month_bounds(month)
    matched = match_categories(db, user, category) if category else []
    rows = _rows(db, user, start, end, kind=kind, category=matched[0] if len(matched) == 1 else None)
    if category and len(matched) > 1:
        rows = [r for r in rows if r.category in matched]
    if text:
        probe = text.strip().lower()
        rows = [r for r in rows if probe in (r.description or "").lower()]
    if payment_method:
        probe = payment_method.strip().lower()
        rows = [r for r in rows if (r.payment_method or "").lower() == probe]
    total = _total(rows)
    rows.sort(key=lambda r: (r.txn_date, r.id), reverse=True)
    return {
        "status": "ok" if rows else ("no_data" if not month and not category and not text else "no_data_for_category"),
        "count": len(rows),
        "total": total,
        "transactions": [
            {"date": r.txn_date.isoformat(), "kind": r.kind, "amount": round(float(r.amount or 0), 2),
             "category": r.category, "description": r.description, "paid_with": r.payment_method}
            for r in rows[:limit]
        ],
        "filters": {"text": text, "category": category, "month": month, "kind": kind,
                    "payment_method": payment_method},
    }


def highest_transactions(db: Session, user, kind: str = "expense", month: str | None = None, limit: int = 3) -> dict:
    start = end = None
    if month:
        start, end = month_bounds(month)
    rows = _rows(db, user, start, end, kind=kind)
    if not rows:
        return {"status": "no_data", "month": month}
    rows.sort(key=lambda r: float(r.amount or 0), reverse=True)
    return {
        "status": "ok",
        "items": [{"date": r.txn_date.isoformat(), "amount": round(float(r.amount or 0), 2),
                   "category": r.category, "description": r.description} for r in rows[:limit]],
    }


def summary(db: Session, user, month: str | None = None) -> dict:
    month = month or current_month()
    start, end = month_bounds(month)
    rows = _rows(db, user, start, end)
    income = _total([r for r in rows if r.kind == "income"])
    expense = _total([r for r in rows if r.kind == "expense"])
    return {
        "status": "ok",
        "month": month,
        "income": income,
        "expense": expense,
        "savings": round(income - expense, 2),
        "savings_rate": round((income - expense) / income * 100, 1) if income else None,
        "count": len(rows),
    }
