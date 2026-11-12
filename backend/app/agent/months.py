"""Which month is a question about?

The assistant gets one month's category breakdown plus twelve months of totals.
A question like "how much did I spend on Dining Out in June?" has to move that
focus to June, otherwise the model answers from the current month's numbers —
which is exactly how a real spend got reported as zero.

No regex word boundaries here on purpose: `\\b` inside a non-raw string is a
backspace character, and that failure mode is silent (the pattern matches
nothing and every month resolves to None).
"""

from __future__ import annotations

from datetime import date, timedelta

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Longest names first so "september" is not consumed as "sep".
_ORDERED = sorted(MONTH_NAMES, key=len, reverse=True)


def _words(text: str) -> list[str]:
    cleaned = []
    current = []
    for char in (text or "").lower():
        if char.isalnum() or char == "-":
            current.append(char)
        elif current:
            cleaned.append("".join(current))
            current = []
    if current:
        cleaned.append("".join(current))
    return cleaned


def resolve_focus_month(message: str, today: date | None = None) -> str | None:
    """Return "YYYY-MM" for the month the question names, else None (current month)."""
    today = today or date.today()
    words = _words(message)

    # 2026-06 / 2026/6 / june 2026
    for word in words:
        if len(word) == 7 and word[4] == "-" and word[:4].isdigit() and word[5:].isdigit():
            year, month = int(word[:4]), int(word[5:])
            if 2000 <= year <= 2099 and 1 <= month <= 12:
                return f"{year:04d}-{month:02d}"

    if "month" in words:
        if "last" in words or "previous" in words:
            return (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        if "this" in words or "current" in words:
            return today.strftime("%Y-%m")

    for index, word in enumerate(words):
        number = MONTH_NAMES.get(word)
        if not number:
            continue
        # A year written next to the month wins: "june 2025".
        for nearby in words[index + 1:index + 3] + words[max(0, index - 2):index]:
            if len(nearby) == 4 and nearby.isdigit() and 2000 <= int(nearby) <= 2099:
                return f"{int(nearby):04d}-{number:02d}"
        # Otherwise the most recent occurrence of that month.
        year = today.year if number <= today.month else today.year - 1
        return f"{year:04d}-{number:02d}"

    return None
