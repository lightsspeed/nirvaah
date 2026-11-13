"""Money as Decimal, quantised to paise (two decimal places, ROUND_HALF_UP).

PostgreSQL stores every monetary column as ``numeric(14,2)`` and SQLAlchemy hands
back ``Decimal``. This module is the single place that converts, rounds, range-
checks and serialises those values, so the rule is stated once instead of being
re-derived (differently) at each call site:

* two decimal places by quantisation, never by truncation;
* ``ROUND_HALF_UP`` — 2.675 becomes 2.68, which is what a person expects from a
  price, not Python's ``round()`` (half-even on the binary value, so 2.67);
* ``numeric(14,2)``'s ceiling (999,999,999,999.99) is enforced before the write,
  not left for PostgreSQL to reject with "numeric field overflow";
* a value that quantises to zero is a rejectable input where the contract says
  "must be more than zero", so a 0.004 transaction never silently becomes 0.00;
* floats are read through their shortest decimal representation
  (``Decimal(str(value))``), so ``10.005`` means the ten-point-zero-zero-five a
  client typed, not the 10.004999999999999893… the double actually holds.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


CENT = Decimal("0.01")
HALF_CENT = Decimal("0.005")         # anything at or beyond this rounds out of range
ZERO = Decimal("0.00")
MAX = Decimal("999999999999.99")     # numeric(14,2) ceiling
MIN = Decimal("-999999999999.99")
# Past this the decimal context cannot quantise to paise at all, so the value is
# refused as an amount instead of surfacing decimal.InvalidOperation.
QUANTISE_CEILING = Decimal("1E+26")


class MoneyError(ValueError):
    """A value that cannot be stored as money."""


def _parse(value: Any) -> Decimal | None:
    """Read a value as a finite Decimal without rounding; None means "no value"."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise MoneyError("a boolean is not an amount")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MoneyError(f"{value!r} is not a monetary amount") from exc
    if not amount.is_finite():
        raise MoneyError("amount must be a finite number")
    return amount


def _quantise(value: Any) -> Decimal | None:
    """Parse and quantise to paise with ROUND_HALF_UP; None means "no value"."""
    amount = _parse(value)
    if amount is None:
        return None
    if abs(amount) >= QUANTISE_CEILING:
        raise MoneyError(f"{value!r} is too large to be an amount")
    try:
        return amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        # Never let a decimal-context error escape as a 500; it is bad input.
        raise MoneyError(f"{value!r} is not a representable amount") from exc


def to_money(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    """Quantise ``value`` to paise with ROUND_HALF_UP; None when there is no value.

    Accepts Decimal, int, float, numeric strings and None. Anything else — a
    bool, a non-numeric string, NaN, ±Infinity — raises MoneyError rather than
    being coerced to zero. The ``numeric(14,2)`` ceiling is enforced on writes
    (:func:`require_money`) and by the column itself, not here: a *sum* of stored
    amounts may legitimately exceed any single column's range.
    """
    amount = _quantise(value)
    return default if amount is None else amount


def require_money(value: Any, *, field: str = "amount", positive: bool = False,
                  maximum: Decimal = MAX) -> Decimal:
    """Like :func:`to_money`, but for a write: present, in range, and signed as agreed.

    ``positive=True`` is the transaction/budget/limit case: the amount must still
    be greater than zero *after* quantisation, which is what rejects 0.004.
    """
    raw = _parse(value)
    if raw is None:
        raise MoneyError(f"{field} is required")
    # Refuse what cannot round into the column before rounding it: a value at or
    # beyond MAX+0.005 rounds up and out of range, so it is rejected as given.
    if abs(raw) >= maximum + HALF_CENT:
        raise MoneyError(f"{field} must be between -{maximum} and {maximum}")
    amount = _quantise(raw)
    if amount > maximum or amount < -maximum:
        raise MoneyError(f"{field} must be between -{maximum} and {maximum}")
    if positive and amount <= ZERO:
        raise MoneyError(f"{field} must be more than zero")
    if not positive and amount < ZERO:
        raise MoneyError(f"{field} must not be negative")
    return amount


def total(values) -> Decimal:
    """Sum monetary values in Decimal, ignoring None entries."""
    result = ZERO
    for value in values:
        amount = _quantise(value)
        if amount is not None:
            result += amount
    return result


def number(value: Any, *, default: Decimal | None = None):
    """The JSON boundary: a Decimal becomes a JSON number (never a string).

    ``None`` stays ``None`` — that is how a nullable journal amount survives —
    and an unquantised value is quantised first so the wire never carries a
    third decimal.
    """
    amount = _quantise(value)
    return default if amount is None else float(amount)


def json_numbers(payload: Any):
    """Recursively turn Decimal leaves into floats, for ``json.dumps`` and HTTP.

    Deliberate and narrow: only ``Decimal`` changes type. Nothing is stringified,
    so a snapshot keeps its numeric shape while staying JSON-serialisable.
    """
    if isinstance(payload, Decimal):
        return float(payload)
    if isinstance(payload, dict):
        return {key: json_numbers(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [json_numbers(value) for value in payload]
    return payload
