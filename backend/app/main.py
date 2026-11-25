import json
import math
import os
import re
import uuid
from datetime import date, timedelta
from calendar import monthrange
from urllib.parse import quote
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func
from .database import Base, engine, get_db
from . import models, schemas
from . import money
from .timeutil import iso_utc, utcnow
from .tz import user_today
from .security import hash_password, verify_password, create_access_token, get_current_user
from .agent.api import router as assistant_router
from .agent.tasks import set_done

Base.metadata.create_all(bind=engine)
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
app = FastAPI(title="Nirvaah API", version=APP_VERSION)
app.include_router(assistant_router)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:5173", "http://127.0.0.1:3000", "http://127.0.0.1:3001"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# Fields whose *value* must never be echoed back in a validation error.
SECRET_FIELDS = frozenset({
    "password", "current_password", "new_password", "confirm_password",
    "token", "access_token", "refresh_token", "id_token", "api_token",
    "secret", "client_secret", "api_key", "authorization",
})


def _scrub(value):
    """Recursively replace the value of every secret key in a mapping."""
    if isinstance(value, dict):
        return {key: ("[redacted]" if str(key).lower() in SECRET_FIELDS else _scrub(item))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


def _redact(errors):
    """Remove a secret's value from a validation error before it leaves the app.

    Pydantic quotes the offending input in ``detail[].input``; for a password or a
    token that would put the secret in the response, and in any log that records
    the body. A "field required" error quotes the *whole* body, so a mapping input
    is scrubbed key by key as well. Location, type and message are kept, so the
    client still learns which field failed and why.
    """
    for error in errors:
        parts = error.get("loc") or ()
        if any(str(part).lower() in SECRET_FIELDS for part in parts):
            if "input" in error:
                error["input"] = "[redacted]"
        elif "input" in error:
            error["input"] = _scrub(error["input"])
    return errors


def _json_safe(value):
    """A JSON-encodable copy of a payload, with non-finite floats written as text.

    A rejected request is echoed back in ``detail[].input``. Python parses ``NaN``
    and ``Infinity`` in a JSON body, but refuses to encode them again, which turned
    a correct 422 into a 500. The amount was already refused; this only makes the
    refusal serialisable.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    detail = _json_safe(_redact(jsonable_encoder(exc.errors())))
    return JSONResponse(status_code=422, content={"detail": detail})


def owned(db, model, item_id, user):
    item = db.query(model).filter(model.id == item_id, model.user_id == user.id).first()
    if not item:
        raise HTTPException(404, "Record not found")
    return item

@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/api/version")
def version():
    return {"name": "Nirvaah", "version": APP_VERSION, "api": "/api", "build": os.getenv("BUILD_SHA", "")}

@app.post("/api/auth/register")
def register(data: schemas.RegisterIn, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == data.email).first():
        raise HTTPException(409, "Email already registered")
    user = models.User(name=data.name, email=data.email, password_hash=hash_password(data.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.post("/api/auth/login")
def login(data: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": {"id": user.id, "name": user.name, "email": user.email}}

@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "currency": user.currency}

def month_bounds(month: str | None) -> tuple[date, date] | None:
    """First day of ``month`` (YYYY-MM) and the first day of the month after it.

    Month filters use ``txn_date >= start AND txn_date < end`` so PostgreSQL can
    use the (user_id, txn_date) index. ``to_char(txn_date, 'YYYY-MM') = month``
    wrapped the column in a function and forced a scan of every row.

    Returns None for anything that is not a plain YYYY-MM month, which keeps the
    old "matches nothing" behaviour for a malformed value.
    """
    if not month or len(month) != 7 or month[4] != "-":
        return None
    try:
        year, mon = int(month[:4]), int(month[5:])
        start = date(year, mon, 1)
    except ValueError:
        return None
    return start, date(year + (mon == 12), mon % 12 + 1, 1)


def month_conditions(month: str | None) -> tuple:
    """Filter conditions for one month: inclusive start, exclusive next month."""
    bounds = month_bounds(month)
    if bounds is None:
        return (models.Transaction.id.is_(None),)
    start, end = bounds
    return (models.Transaction.txn_date >= start, models.Transaction.txn_date < end)


def parse_date_param(d_str: str | None) -> date | None:
    if not d_str:
        return None
    try:
        return date.fromisoformat(d_str[:10])
    except Exception:
        return None

@app.get("/api/dashboard")
def dashboard(
    month: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    today: date = Depends(user_today),
):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    s_d = parse_date_param(start_date)
    e_d = parse_date_param(end_date)
    if s_d and e_d:
        q = q.filter(models.Transaction.txn_date >= s_d, models.Transaction.txn_date <= e_d)
        period_label = f"{s_d.isoformat()} to {e_d.isoformat()}"
        budget_month = e_d.strftime("%Y-%m")
    elif month and month.lower() == "all":
        # "all" - get all transactions for this user across all time
        period_label = "All Time"
        budget_month = today.strftime("%Y-%m")
    elif month:
        q = q.filter(*month_conditions(month))
        period_label = month
        budget_month = month
    else:
        # Default: current month stats
        cur_m = today.strftime("%Y-%m")
        q = q.filter(*month_conditions(cur_m))
        period_label = cur_m
        budget_month = cur_m

    txns = q.all()
    income = money.total(t.amount for t in txns if t.kind == "income")
    expenses = money.total(t.amount for t in txns if t.kind == "expense")
    by_category = {}
    for t in txns:
        if t.kind == "expense":
            by_category[t.category] = by_category.get(t.category, money.ZERO) + t.amount
    investments = db.query(models.Investment).filter_by(user_id=user.id).all()
    liabilities = db.query(models.Liability).filter_by(user_id=user.id).all()
    budget_rows = db.query(models.Budget).filter_by(user_id=user.id, month=budget_month).all()
    if not budget_rows:
        # Fallback to any recent budgets if none found for exact month
        budget_rows = db.query(models.Budget).filter_by(user_id=user.id).all()
    budgets = []
    for b in budget_rows:
        spent = by_category.get(b.category, 0)
        budgets.append({"id": b.id, "category": b.category, "monthly_limit": money.number(b.monthly_limit),
                        "spent": money.number(spent), "remaining": money.number(b.monthly_limit - spent)})
    return {
        "period": period_label,
        "month": month or budget_month,
        "income": money.number(income),
        "expenses": money.number(expenses),
        "savings": money.number(income - expenses),
        "savings_rate": round(float((income - expenses) / income * 100), 1) if income else 0,
        "investment_value": money.number(money.total(i.current_value for i in investments)),
        "investment_cost": money.number(money.total(i.invested_amount for i in investments)),
        "liabilities": money.number(money.total(l.outstanding_amount for l in liabilities)),
        "net_worth": money.number(money.total(i.current_value for i in investments)
                                   - money.total(l.outstanding_amount for l in liabilities)),
        "category_expenses": [{"category": k, "amount": money.number(v)}
                              for k, v in sorted(by_category.items(), key=lambda x: x[1], reverse=True)],
        "budgets": budgets,
        "recent_transactions": [txn_dict(t) for t in sorted(txns, key=lambda x: x.txn_date, reverse=True)[:10]],
        "total_txns": len(txns),
    }

def txn_dict(t):
    return {"id":t.id,"kind":t.kind,"amount":money.number(t.amount),"category":t.category,"description":t.description,"payment_method":t.payment_method,"txn_date":t.txn_date.isoformat()}

@app.get("/api/transactions")
def list_transactions(
    month: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    kind: str | None = None,
    category: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    today: date = Depends(user_today),
):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    s_d = parse_date_param(start_date)
    e_d = parse_date_param(end_date)
    if s_d and e_d:
        q = q.filter(models.Transaction.txn_date >= s_d, models.Transaction.txn_date <= e_d)
    elif month and month.lower() == "all":
        pass  # All time
    elif month:
        q = q.filter(*month_conditions(month))
    else:
        # Default: current month
        q = q.filter(*month_conditions(today.strftime("%Y-%m")))
    
    if kind and kind.lower() in ("income", "expense"):
        q = q.filter(models.Transaction.kind == kind.lower())
    if category and category.lower() != "all":
        q = q.filter(models.Transaction.category == category)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter((models.Transaction.description.ilike(term)) | (models.Transaction.category.ilike(term)))
        
    return [txn_dict(t) for t in q.order_by(models.Transaction.txn_date.desc(), models.Transaction.id.desc()).all()]

@app.post("/api/transactions")
def create_transaction(data: schemas.TransactionIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if data.kind not in ("income", "expense"): raise HTTPException(400, "kind must be income or expense")
    item = models.Transaction(user_id=user.id, **data.model_dump())
    db.add(item); db.commit(); db.refresh(item); return txn_dict(item)

@app.put("/api/transactions/{item_id}")
def update_transaction(item_id: int, data: schemas.TransactionIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    item = owned(db, models.Transaction, item_id, user)
    if data.kind not in ("income", "expense"): raise HTTPException(400, "kind must be income or expense")
    for k,v in data.model_dump().items(): setattr(item,k,v)
    db.commit(); db.refresh(item); return txn_dict(item)

@app.delete("/api/transactions/{item_id}")
def delete_transaction(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    item=owned(db,models.Transaction,item_id,user); db.delete(item); db.commit(); return {"deleted":True}

@app.get("/api/budgets")
def budgets(month: str | None = None, db: Session=Depends(get_db), user=Depends(get_current_user),
            today: date = Depends(user_today)):
    q = db.query(models.Budget).filter_by(user_id=user.id)
    if month and month.lower() != "all":
        month_budgets = q.filter(models.Budget.month == month).order_by(models.Budget.month.desc()).all()
        budget_items = month_budgets if month_budgets else q.order_by(models.Budget.month.desc()).all()
    else:
        budget_items = q.order_by(models.Budget.month.desc()).all()
    res = []
    for x in budget_items:
        m = month if (month and month.lower() != "all") else (x.month or today.strftime("%Y-%m"))
        if engine.dialect.name == "sqlite":
            spent = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
                models.Transaction.user_id == user.id,
                models.Transaction.kind == "expense",
                models.Transaction.category == x.category,
                func.strftime("%Y-%m", models.Transaction.txn_date) == m
            ).scalar()
        else:
            spent = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
                models.Transaction.user_id == user.id,
                models.Transaction.kind == "expense",
                models.Transaction.category == x.category,
                func.to_char(models.Transaction.txn_date, "YYYY-MM") == m
            ).scalar()
        spent = money.to_money(spent, default=money.ZERO)
        res.append({
            "id": x.id,
            "category": x.category,
            "monthly_limit": money.number(x.monthly_limit),
            "month": x.month or m,
            "spent": money.number(spent),
            "remaining": money.number(x.monthly_limit - spent)
        })
    return res

@app.post("/api/budgets")
def add_budget(data: schemas.BudgetIn, db: Session=Depends(get_db), user=Depends(get_current_user)):
    item=models.Budget(user_id=user.id,**data.model_dump()); db.add(item); db.commit(); db.refresh(item); return {"id":item.id,"category":item.category,"monthly_limit":money.number(item.monthly_limit),"month":item.month}

@app.delete("/api/budgets/{item_id}")
def delete_budget(item_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    item=owned(db,models.Budget,item_id,user); db.delete(item); db.commit(); return {"deleted":True}

@app.get("/api/goals")
def goals(db:Session=Depends(get_db), user=Depends(get_current_user)):
    return [{"id":x.id,"name":x.name,"target_amount":money.number(x.target_amount),"saved_amount":money.number(x.saved_amount),"target_date":x.target_date.isoformat() if x.target_date else None} for x in db.query(models.Goal).filter_by(user_id=user.id).all()]

@app.post("/api/goals")
def add_goal(data:schemas.GoalIn, db:Session=Depends(get_db), user=Depends(get_current_user)):
    item=models.Goal(user_id=user.id,**data.model_dump()); db.add(item); db.commit(); db.refresh(item); return {"id":item.id,**data.model_dump()}

@app.delete("/api/goals/{item_id}")
def delete_goal(item_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    item=owned(db,models.Goal,item_id,user); db.delete(item); db.commit(); return {"deleted":True}

@app.get("/api/investments")
def investments(db:Session=Depends(get_db), user=Depends(get_current_user)):
    return [{"id":x.id,"name":x.name,"asset_type":x.asset_type,"invested_amount":money.number(x.invested_amount),"current_value":money.number(x.current_value),"notes":x.notes} for x in db.query(models.Investment).filter_by(user_id=user.id).all()]

@app.post("/api/investments")
def add_investment(data:schemas.InvestmentIn, db:Session=Depends(get_db), user=Depends(get_current_user)):
    item=models.Investment(user_id=user.id,**data.model_dump()); db.add(item); db.commit(); db.refresh(item); return {"id":item.id,**data.model_dump()}

@app.delete("/api/investments/{item_id}")
def delete_investment(item_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    item=owned(db,models.Investment,item_id,user); db.delete(item); db.commit(); return {"deleted":True}

@app.get("/api/liabilities")
def liabilities(db:Session=Depends(get_db), user=Depends(get_current_user)):
    return [{"id":x.id,"name":x.name,"liability_type":x.liability_type,"outstanding_amount":money.number(x.outstanding_amount),"monthly_emi":money.number(x.monthly_emi),"notes":x.notes} for x in db.query(models.Liability).filter_by(user_id=user.id).all()]

@app.post("/api/liabilities")
def add_liability(data:schemas.LiabilityIn, db:Session=Depends(get_db), user=Depends(get_current_user)):
    item=models.Liability(user_id=user.id,**data.model_dump()); db.add(item); db.commit(); db.refresh(item); return {"id":item.id,**data.model_dump()}

@app.delete("/api/liabilities/{item_id}")
def delete_liability(item_id:int, db:Session=Depends(get_db), user=Depends(get_current_user)):
    item=owned(db,models.Liability,item_id,user); db.delete(item); db.commit(); return {"deleted":True}

# ── Cashflow: last N months of income vs expense ─────────────────────────────
@app.get("/api/cashflow")
def cashflow(months: int = Query(default=6, ge=1, le=24), db: Session = Depends(get_db),
             user=Depends(get_current_user), today: date = Depends(user_today)):
    import calendar as cal_mod
    today_d = today
    result = []
    for i in range(months - 1, -1, -1):
        y = today_d.year
        m = today_d.month - i
        while m <= 0:
            m += 12
            y -= 1
        month_str = f"{y:04d}-{m:02d}"
        if engine.dialect.name == "sqlite":
            txns = db.query(models.Transaction).filter(
                models.Transaction.user_id == user.id,
                func.strftime("%Y-%m", models.Transaction.txn_date) == month_str
            ).all()
        else:
            txns = db.query(models.Transaction).filter(
                models.Transaction.user_id == user.id,
                func.to_char(models.Transaction.txn_date, "YYYY-MM") == month_str
            ).all()
        inc = money.number(money.total(t.amount for t in txns if t.kind == "income"))
        exp = money.number(money.total(t.amount for t in txns if t.kind == "expense"))
        label = f"{cal_mod.month_abbr[m]} '{str(y)[2:]}"
        result.append({"month": month_str, "label": label, "income": inc, "expense": exp})
    return result

# ── Analytics: category breakdown for a date range ───────────────────────────
@app.get("/api/analytics")
def analytics(
    from_month: str = Query(default=None, alias="from"),
    to_month: str = Query(default=None, alias="to"),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    today: date = Depends(user_today),
):
    q = db.query(models.Transaction).filter_by(user_id=user.id)
    s_d = parse_date_param(start_date)
    e_d = parse_date_param(end_date)
    if s_d and e_d:
        q = q.filter(models.Transaction.txn_date >= s_d, models.Transaction.txn_date <= e_d)
        from_label = s_d.isoformat()
        to_label = e_d.isoformat()
    elif from_month and from_month.lower() != "all":
        if not to_month:
            to_month = from_month
        start_bounds = month_bounds(from_month)
        end_bounds = month_bounds(to_month)
        if start_bounds is None or end_bounds is None:
            q = q.filter(models.Transaction.id.is_(None))
        else:
            # Whole months: from the 1st of `from` up to (not including) the 1st
            # of the month after `to`.
            q = q.filter(
                models.Transaction.txn_date >= start_bounds[0],
                models.Transaction.txn_date < end_bounds[1],
            )
        from_label = from_month
        to_label = to_month
    elif from_month and from_month.lower() == "all":
        from_label = "All Time"
        to_label = "Present"
    else:
        # Default: current month
        cur_m = today.strftime("%Y-%m")
        q = q.filter(*month_conditions(cur_m))
        from_label = cur_m
        to_label = cur_m

    txns = q.all()
    by_cat = {}
    by_cat_cnt = {}
    by_payment_exp = {}
    by_payment_inc = {}
    by_payment_cnt = {}
    by_payment_exp_cnt = {}
    by_payment_inc_cnt = {}

    exp_txns_count = 0
    inc_txns_count = 0

    for t in txns:
        pm = t.payment_method or "Other"
        by_payment_cnt[pm] = by_payment_cnt.get(pm, 0) + 1
        if t.kind == "expense":
            exp_txns_count += 1
            by_cat[t.category] = by_cat.get(t.category, money.ZERO) + t.amount
            by_cat_cnt[t.category] = by_cat_cnt.get(t.category, 0) + 1
            by_payment_exp[pm] = by_payment_exp.get(pm, money.ZERO) + t.amount
            by_payment_exp_cnt[pm] = by_payment_exp_cnt.get(pm, 0) + 1
        elif t.kind == "income":
            inc_txns_count += 1
            by_payment_inc[pm] = by_payment_inc.get(pm, money.ZERO) + t.amount
            by_payment_inc_cnt[pm] = by_payment_inc_cnt.get(pm, 0) + 1

    total_exp = money.total(by_cat.values())
    total_inc = money.total(t.amount for t in txns if t.kind == "income")
    avg_expense_per_txn = money.number(total_exp / exp_txns_count) if exp_txns_count else 0
    avg_income_per_txn = money.number(total_inc / inc_txns_count) if inc_txns_count else 0

    categories = [
        {
            "category": k,
            "amount": money.number(v),
            "txns": by_cat_cnt.get(k, 0),
            "avg": money.number(v / by_cat_cnt[k]) if by_cat_cnt.get(k, 0) else 0,
            "pct": round(float(v / total_exp * 100), 1) if total_exp else 0,
        }
        for k, v in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
    ]

    all_methods = set(by_payment_exp.keys()) | set(by_payment_inc.keys())
    payment_breakdown = [
        {
            "payment_method": k,
            "amount": money.number(by_payment_exp.get(k, money.ZERO)),
            "income": money.number(by_payment_inc.get(k, money.ZERO)),
            "net": money.number(by_payment_inc.get(k, money.ZERO) - by_payment_exp.get(k, money.ZERO)),
            "txns": by_payment_cnt.get(k, 0),
            "exp_txns": by_payment_exp_cnt.get(k, 0),
            "inc_txns": by_payment_inc_cnt.get(k, 0),
            "avg": money.number(by_payment_exp.get(k, money.ZERO) / by_payment_exp_cnt[k]) if by_payment_exp_cnt.get(k, 0) else 0,
            "avg_income": money.number(by_payment_inc.get(k, money.ZERO) / by_payment_inc_cnt[k]) if by_payment_inc_cnt.get(k, 0) else 0,
            "avg_overall": money.number((by_payment_exp.get(k, money.ZERO) + by_payment_inc.get(k, money.ZERO)) / by_payment_cnt[k]) if by_payment_cnt.get(k, 0) else 0,
            "pct": round(float(by_payment_exp.get(k, money.ZERO) / total_exp * 100), 1) if total_exp else 0,
        }
        for k in sorted(all_methods, key=lambda x: (by_payment_exp.get(x, 0), by_payment_cnt.get(x, 0)), reverse=True)
    ]

    return {
        "from": from_label,
        "to": to_label,
        "total_income": money.number(total_inc),
        "total_expense": money.number(total_exp),
        "total_txns": len(txns),
        "exp_txns": exp_txns_count,
        "inc_txns": inc_txns_count,
        "avg_expense_per_txn": avg_expense_per_txn,
        "avg_income_per_txn": avg_income_per_txn,
        "category_breakdown": categories,
        "payment_breakdown": payment_breakdown,
    }

# ── All-time transaction date range (for pickers) ────────────────────────────
@app.get("/api/transactions/range")
def tx_range(db: Session = Depends(get_db), user=Depends(get_current_user)):
    mn = db.query(func.min(models.Transaction.txn_date)).filter_by(user_id=user.id).scalar()
    mx = db.query(func.max(models.Transaction.txn_date)).filter_by(user_id=user.id).scalar()
    cnt = db.query(func.count(models.Transaction.id)).filter_by(user_id=user.id).scalar()
    return {
        "min": mn.strftime("%Y-%m") if mn else None,
        "max": mx.strftime("%Y-%m") if mx else None,
        "min_date": mn.isoformat() if mn else None,
        "max_date": mx.isoformat() if mx else None,
        "total_count": cnt or 0,
    }


# ══════════════════════════════════════════════════════════════════════════
# Life records — notes, tasks, journal. Server-side so they survive a browser
# wipe, a new device and a container restart (Postgres volume).
# ══════════════════════════════════════════════════════════════════════════

def _iso(value):
    return value.isoformat() if value else None


def _to_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _to_tags(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return json.dumps([str(v).strip() for v in value if str(v).strip()])
    return "[]"


def _from_tags(value):
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _num(value):
    """A nullable monetary value: quantised to paise, None when absent.

    A journal entry may carry no amount at all; anything that is present must be a
    real amount, so a value the column cannot hold is refused instead of being
    dropped to NULL.
    """
    if value in (None, "", False):
        return None
    try:
        return money.require_money(value, field="amount")
    except money.MoneyError as exc:
        raise HTTPException(422, str(exc)) from exc


# ── Note / task attachments ────────────────────────────────────────────────
# The bytes are stored in the attachments table; note and task payloads carry
# only the metadata the UI needs, so listing a collection never loads a blob.
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENTS_PER_RECORD = 12
MAX_ATTACHMENTS_TOTAL_BYTES = 24 * 1024 * 1024
ATTACHMENT_KINDS = {"note", "task"}
SAFE_INLINE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _attachment_meta(a):
    return {"id": a.id, "name": a.name, "mime": a.mime, "size": a.size}


def _attachments_by_owner(db: Session, user, kind: str, owner_ids) -> dict[str, list]:
    ids = [str(value) for value in owner_ids if value]
    if not ids:
        return {}
    rows = (
        db.query(
            models.Attachment.id,
            models.Attachment.owner_id,
            models.Attachment.name,
            models.Attachment.mime,
            models.Attachment.size,
        )
        .filter(
            models.Attachment.user_id == user.id,
            models.Attachment.owner_kind == kind,
            models.Attachment.owner_id.in_(ids),
        )
        .order_by(models.Attachment.created_at.asc())
        .all()
    )
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.owner_id, []).append(
            {"id": row.id, "name": row.name, "mime": row.mime, "size": row.size}
        )
    return grouped


def _delete_attachments(db: Session, user, kind: str, owner_id: str) -> None:
    db.query(models.Attachment).filter(
        models.Attachment.user_id == user.id,
        models.Attachment.owner_kind == kind,
        models.Attachment.owner_id == owner_id,
    ).delete(synchronize_session=False)


def _touch_owner(db: Session, user, kind: str, owner_id: str) -> None:
    """Attaching or removing a file changes the record, so other devices that
    poll /sync/version must see a new stamp even when no field was edited."""
    model = models.Note if kind == "note" else models.Task
    row = db.get(model, owner_id)
    if row and row.user_id == user.id:
        row.updated_at = utcnow()


def _note_out(n: models.Note, attachments: list | None = None):
    return {
        "id": n.id, "title": n.title, "body": n.body, "category": n.category,
        "tags": _from_tags(n.tags), "pinned": n.pinned, "archived": n.archived,
        "attachments": attachments or [],
        "createdAt": iso_utc(n.created_at),
        "updatedAt": iso_utc(n.updated_at),
    }


def _task_out(t: models.Task, attachments: list | None = None):
    return {
        "id": t.id, "text": t.text, "notes": t.notes, "done": t.done,
        "priority": t.priority, "category": t.category, "due": _iso(t.due),
        "attachments": attachments or [],
        "createdAt": iso_utc(t.created_at),
        "updatedAt": iso_utc(t.updated_at),
    }


@app.post("/api/attachments")
async def upload_attachment(
    file: UploadFile = File(...),
    owner_kind: str = Form(...),
    owner_id: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if owner_kind not in ATTACHMENT_KINDS:
        raise HTTPException(400, "owner_kind must be note or task")
    owner_id = str(owner_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", owner_id):
        raise HTTPException(400, "owner_id is not a valid record id")
    blob = await file.read(MAX_ATTACHMENT_BYTES + 1)
    if not blob:
        raise HTTPException(400, "The file is empty")
    if len(blob) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "Attachments are limited to 8 MB per file")
    existing = db.query(
        func.count(models.Attachment.id),
        func.coalesce(func.sum(models.Attachment.size), 0),
    ).filter(
        models.Attachment.user_id == user.id,
        models.Attachment.owner_kind == owner_kind,
        models.Attachment.owner_id == owner_id,
    ).one()
    if existing[0] >= MAX_ATTACHMENTS_PER_RECORD:
        raise HTTPException(422, f"A record can hold {MAX_ATTACHMENTS_PER_RECORD} attachments")
    if int(existing[1] or 0) + len(blob) > MAX_ATTACHMENTS_TOTAL_BYTES:
        raise HTTPException(413, "This record's attachments are limited to 24 MB in total")
    name = str(file.filename or "attachment").replace("\\", "/").split("/")[-1][:255] or "attachment"
    mime = str(file.content_type or "application/octet-stream").split(";")[0].strip()[:120]
    row = models.Attachment(
        id=uuid.uuid4().hex,
        user_id=user.id,
        owner_kind=owner_kind,
        owner_id=owner_id,
        name=name,
        mime=mime or "application/octet-stream",
        size=len(blob),
        data=blob,
    )
    db.add(row)
    _touch_owner(db, user, owner_kind, owner_id)
    db.commit()
    db.refresh(row)
    return _attachment_meta(row)


@app.get("/api/attachments/{attachment_id}")
def get_attachment(
    attachment_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = (
        db.query(models.Attachment)
        .filter(models.Attachment.id == attachment_id, models.Attachment.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Attachment not found")
    headers = {
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    }
    if row.mime in SAFE_INLINE_MIMES:
        headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(row.name, safe='')}"
        return Response(content=bytes(row.data), media_type=row.mime, headers=headers)
    # Anything else is downloaded, never rendered in the app's origin.
    headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(row.name, safe='')}"
    return Response(content=bytes(row.data), media_type="application/octet-stream", headers=headers)


@app.delete("/api/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = (
        db.query(models.Attachment)
        .filter(models.Attachment.id == attachment_id, models.Attachment.user_id == user.id)
        .first()
    )
    if row:
        _touch_owner(db, user, row.owner_kind, row.owner_id)
        db.delete(row)
        db.commit()
    return {"ok": True}


def _journal_out(e: models.JournalEntry):
    return {
        "id": e.id, "title": e.title, "description": e.description,
        "category": e.category, "mood": e.mood, "amount": money.number(e.amount),
        "date": _iso(e.event_date), "tags": _from_tags(e.tags),
        "createdAt": iso_utc(e.created_at),
        "updatedAt": iso_utc(e.updated_at),
    }


def _apply_note(row, data):
    if "title" in data:
        row.title = str(data["title"])[:255]
    if "body" in data:
        row.body = str(data["body"])
    if "category" in data:
        row.category = str(data["category"])[:60]
    if "tags" in data:
        row.tags = _to_tags(data["tags"])
    if "pinned" in data:
        row.pinned = bool(data["pinned"])
    if "archived" in data:
        row.archived = bool(data["archived"])
    return row


def _apply_task(row, data):
    if "text" in data:
        row.text = str(data["text"])[:500]
    if "notes" in data:
        row.notes = str(data["notes"])
    if "done" in data:
        # Same transition rule as the assistant: set once, cleared on reopen.
        set_done(row, bool(data["done"]))
    if "priority" in data:
        row.priority = str(data["priority"])[:12]
    if "category" in data:
        row.category = str(data["category"])[:60]
    if "due" in data:
        row.due = _to_date(data["due"])
    return row


def _apply_journal(row, data):
    if "title" in data:
        row.title = str(data["title"])[:255]
    if "description" in data:
        row.description = str(data["description"])
    if "category" in data:
        row.category = str(data["category"])[:60]
    if "mood" in data:
        row.mood = str(data["mood"])[:20]
    if "amount" in data:
        row.amount = _num(data["amount"])
    if "tags" in data:
        row.tags = _to_tags(data["tags"])
    if "date" in data:
        row.event_date = _to_date(data["date"])
    return row


@app.get("/api/notes")
def list_notes(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(models.Note).filter(models.Note.user_id == user.id).order_by(models.Note.updated_at.desc()).all()
    attachments = _attachments_by_owner(db, user, "note", [n.id for n in rows])
    return [_note_out(n, attachments.get(n.id, [])) for n in rows]


@app.post("/api/notes")
def upsert_note(payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if payload.get("id") and _is_deleted(db, user, str(payload.get("id"))):
        return {"ok": True, "skipped": "deleted"}
    row = db.get(models.Note, str(payload.get("id"))) if payload.get("id") else None
    if row and row.user_id != user.id:
        raise HTTPException(404, "Record not found")
    if not row:
        row = models.Note(id=str(payload.get("id") or uuid.uuid4()), user_id=user.id)
        db.add(row)
    _apply_note(row, payload)
    row.updated_at = utcnow()
    db.commit(); db.refresh(row)
    attachments = _attachments_by_owner(db, user, "note", [row.id])
    return _note_out(row, attachments.get(row.id, []))


@app.delete("/api/notes/{item_id}")
def delete_note(item_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(models.Note).filter(models.Note.id == item_id, models.Note.user_id == user.id).first()
    _tombstone(db, user, 'notes', item_id)
    if row:
        _delete_attachments(db, user, "note", row.id)
        db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/api/tasks")
def list_tasks(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(models.Task).filter(models.Task.user_id == user.id).order_by(models.Task.created_at.desc()).all()
    attachments = _attachments_by_owner(db, user, "task", [t.id for t in rows])
    return [_task_out(t, attachments.get(t.id, [])) for t in rows]


@app.post("/api/tasks")
def upsert_task(payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if payload.get("id") and _is_deleted(db, user, str(payload.get("id"))):
        return {"ok": True, "skipped": "deleted"}
    row = db.get(models.Task, str(payload.get("id"))) if payload.get("id") else None
    if row and row.user_id != user.id:
        raise HTTPException(404, "Record not found")
    if not row:
        row = models.Task(id=str(payload.get("id") or uuid.uuid4()), user_id=user.id)
        db.add(row)
    _apply_task(row, payload)
    row.updated_at = utcnow()
    db.commit(); db.refresh(row)
    attachments = _attachments_by_owner(db, user, "task", [row.id])
    return _task_out(row, attachments.get(row.id, []))


@app.delete("/api/tasks/{item_id}")
def delete_task(item_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(models.Task).filter(models.Task.id == item_id, models.Task.user_id == user.id).first()
    _tombstone(db, user, 'tasks', item_id)
    if row:
        _delete_attachments(db, user, "task", row.id)
        db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/api/journal")
def list_journal(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(models.JournalEntry).filter(models.JournalEntry.user_id == user.id).order_by(models.JournalEntry.event_date.desc()).all()
    return [_journal_out(e) for e in rows]


@app.post("/api/journal")
def upsert_journal(payload: dict, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if payload.get("id") and _is_deleted(db, user, str(payload.get("id"))):
        return {"ok": True, "skipped": "deleted"}
    row = db.get(models.JournalEntry, str(payload.get("id"))) if payload.get("id") else None
    if row and row.user_id != user.id:
        raise HTTPException(404, "Record not found")
    if not row:
        row = models.JournalEntry(id=str(payload.get("id") or uuid.uuid4()), user_id=user.id)
        db.add(row)
    _apply_journal(row, payload)
    row.updated_at = utcnow()
    db.commit(); db.refresh(row)
    return _journal_out(row)


@app.delete("/api/journal/{item_id}")
def delete_journal(item_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.query(models.JournalEntry).filter(models.JournalEntry.id == item_id, models.JournalEntry.user_id == user.id).first()
    _tombstone(db, user, 'journal', item_id)
    if row:
        db.delete(row)
    db.commit()
    return {"ok": True}


# ── Tombstones ───────────────────────────────────────────────────────────────
# A delete has to stick across devices: the other device still holds the record
# in its cache and would otherwise push it straight back.

def _tombstone(db, user, kind, item_id):
    row = db.get(models.Deletion, item_id)
    if row and row.user_id == user.id:
        return
    db.add(models.Deletion(id=item_id, user_id=user.id, kind=kind))


def _is_deleted(db, user, item_id):
    row = db.get(models.Deletion, item_id)
    return bool(row and row.user_id == user.id)


@app.get("/api/sync/version")
def sync_version(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """A tiny fingerprint of this user's life records. Clients poll it and
    re-hydrate only when it changes, which is what makes two devices feel
    live without a websocket, a broker or a per-connection process."""
    def stamp(model):
        latest, count = db.query(func.max(model.updated_at), func.count()).filter(model.user_id == user.id).one()
        return f"{latest.isoformat() if latest else '-'}:{count or 0}"

    dead = db.query(func.count()).select_from(models.Deletion).filter(models.Deletion.user_id == user.id).scalar()
    parts = [stamp(models.Note), stamp(models.Task), stamp(models.JournalEntry), str(dead or 0)]
    return {"version": "|".join(parts)}


@app.get("/api/deletions")
def list_deletions(kind: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    query = db.query(models.Deletion).filter(models.Deletion.user_id == user.id)
    if kind:
        query = query.filter(models.Deletion.kind == kind)
    return [{"id": d.id, "kind": d.kind} for d in query.all()]
