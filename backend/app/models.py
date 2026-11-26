from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .timeutil import utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # income | expense
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(255), default="")
    payment_method: Mapped[str] = mapped_column(String(40), default="SBI")
    txn_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(80))
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM

class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    saved_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)

class Investment(Base):
    __tablename__ = "investments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    asset_type: Mapped[str] = mapped_column(String(50))
    invested_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    current_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    notes: Mapped[str] = mapped_column(Text, default="")

class Liability(Base):
    __tablename__ = "liabilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    liability_type: Mapped[str] = mapped_column(String(50))
    outstanding_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    monthly_emi: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


# ── Life records (notes / tasks / journal) ───────────────────────────────────
# Client-generated ids keep local-first behaviour: the browser can create a
# record offline and the same id is the primary key server-side.
class Note(Base):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), default="Personal")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[str] = mapped_column(String(12), default="medium")
    category: Mapped[str] = mapped_column(String(60), default="Personal")
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Set when a task becomes complete, cleared when it is reopened. NULL for
    # tasks completed before this column existed — their date is unknowable.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), default="Life")
    mood: Mapped[str] = mapped_column(String(20), default="steady")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tags: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Habit(Base):
    """A habit and the days it was checked, as a local-first life record.

    It deliberately has no link to the ledger: a habit is a personal routine,
    not money. Checks are a JSON list of calendar days (YYYY-MM-DD) so one row
    carries the whole history and the sync payload stays small.
    """
    __tablename__ = "habits"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    category: Mapped[str] = mapped_column(String(60), default="Personal")
    target: Mapped[int] = mapped_column(Integer, default=7)  # days per week
    checks: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Trade(Base):
    """A trade journal entry. It is never read by the dashboard, budgets or reports."""
    __tablename__ = "trades"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(40), default="")
    side: Mapped[str] = mapped_column(String(8), default="buy")  # buy | sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    fees: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    setup: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Deletion(Base):
    """A tombstone. Deleting on one device must not be undone by another
    device that still holds the record in its local cache."""
    __tablename__ = "deletions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    deleted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Attachment(Base):
    """An image or file attached to a note or a task.

    The bytes live here rather than in the note/task row so listing either
    collection never reads a blob. The owner is a client-generated id, which
    lets an attachment be uploaded before the note or task itself exists (the
    editor can attach first and save afterwards); the owner kind + id pair is
    re-read from this table when the record is listed.
    """
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner_kind: Mapped[str] = mapped_column(String(12), index=True)  # note | task
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ── Assistant: conversations, turns and durable memory ──────────────────────
class Conversation(Base):
    __tablename__ = "chat_conversations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="New conversation")
    provider: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("chat_conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(40), default="")
    # Applied / pending / failed actions for this turn, as JSON.
    meta: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemoryFact(Base):
    """A durable fact the user asked the assistant to keep — a preference, a
    standing constraint, a name. Recalled into every later turn."""
    __tablename__ = "chat_memories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fact: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChatFocus(Base):
    """The record the conversation is currently about.

    "Make it high priority", "move that to Sunday", "delete it" all need a
    referent. The database keeps it (not the prompt) so a restart cannot make
    the assistant guess, and a topic change overwrites it.
    """
    __tablename__ = "chat_focus"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("chat_conversations.id"), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), default="")
    entity_id: Mapped[str] = mapped_column(String(40), default="")
    label: Mapped[str] = mapped_column(String(255), default="")
    operation: Mapped[str] = mapped_column(String(40), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
