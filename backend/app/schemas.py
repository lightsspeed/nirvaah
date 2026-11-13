from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

from . import money


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TransactionIn(BaseModel):
    kind: str
    amount: Decimal
    category: str
    description: str = ""
    payment_method: str = "SBI"
    txn_date: date

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value):
        # Quantises first: 10.005 -> 10.01, and 0.004 -> 0.00 is then rejected
        # rather than stored as a transaction worth nothing.
        return money.require_money(value, field="amount", positive=True)

class BudgetIn(BaseModel):
    category: str
    monthly_limit: Decimal
    month: str = Field(pattern=r"^\d{4}-\d{2}$")

    @field_validator("monthly_limit", mode="before")
    @classmethod
    def _limit(cls, value):
        return money.require_money(value, field="monthly_limit", positive=True)

class GoalIn(BaseModel):
    name: str
    target_amount: Decimal
    saved_amount: Decimal
    target_date: date | None = None

    @field_validator("target_amount", mode="before")
    @classmethod
    def _target(cls, value):
        return money.require_money(value, field="target_amount", positive=True)

    @field_validator("saved_amount", mode="before")
    @classmethod
    def _saved(cls, value):
        return money.require_money(value, field="saved_amount")

class InvestmentIn(BaseModel):
    name: str
    asset_type: str
    invested_amount: Decimal
    current_value: Decimal
    notes: str = ""

    @field_validator("invested_amount", mode="before")
    @classmethod
    def _invested(cls, value):
        return money.require_money(value, field="invested_amount")

    @field_validator("current_value", mode="before")
    @classmethod
    def _current(cls, value):
        return money.require_money(value, field="current_value")

class LiabilityIn(BaseModel):
    name: str
    liability_type: str
    outstanding_amount: Decimal
    monthly_emi: Decimal
    notes: str = ""

    @field_validator("outstanding_amount", mode="before")
    @classmethod
    def _outstanding(cls, value):
        return money.require_money(value, field="outstanding_amount")

    @field_validator("monthly_emi", mode="before")
    @classmethod
    def _emi(cls, value):
        return money.require_money(value, field="monthly_emi")
