from datetime import date
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TransactionIn(BaseModel):
    kind: str
    amount: float = Field(gt=0)
    category: str
    description: str = ""
    payment_method: str = "SBI"
    txn_date: date

class BudgetIn(BaseModel):
    category: str
    monthly_limit: float = Field(gt=0)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")

class GoalIn(BaseModel):
    name: str
    target_amount: float = Field(gt=0)
    saved_amount: float = Field(ge=0)
    target_date: date | None = None

class InvestmentIn(BaseModel):
    name: str
    asset_type: str
    invested_amount: float = Field(ge=0)
    current_value: float = Field(ge=0)
    notes: str = ""

class LiabilityIn(BaseModel):
    name: str
    liability_type: str
    outstanding_amount: float = Field(ge=0)
    monthly_emi: float = Field(ge=0)
    notes: str = ""
