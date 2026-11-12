"""Structured events and counters for the assistant.

One line of JSON per event on the `nirvaah.agent` logger, plus in-process
counters served by `GET /api/chat/metrics`. Nothing sensitive goes in here —
no API keys, no full transaction lists, only ids and statuses.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from contextlib import contextmanager

log = logging.getLogger("nirvaah.agent")

MAX_LATENCY_SAMPLES = 200
_counters: Counter = Counter()
_latencies: list[float] = []

# Counters that mean "the assistant misled someone" — surfaced first in metrics.
CRITICAL = (
    "false_success",          # a reply claimed a change that never happened
    "verify_failed",          # commit happened but read-back disagreed
    "commit_failed",          # the database refused the write
    "analytics_error",        # a financial question could not be answered from data
)


def inc(name: str, amount: int = 1) -> None:
    _counters[name] += amount


def observe(name: str, seconds: float) -> None:
    _latencies.append(seconds)
    if len(_latencies) > MAX_LATENCY_SAMPLES:
        del _latencies[: len(_latencies) - MAX_LATENCY_SAMPLES]
    log.debug(json.dumps({"event": name, "seconds": round(seconds, 3)}))


def event(name: str, **fields) -> None:
    payload = {"event": name}
    payload.update({k: v for k, v in fields.items() if v not in (None, "")})
    try:
        log.info(json.dumps(payload, default=str))
    except (TypeError, ValueError):  # never lose a request to a log bug
        log.info(json.dumps({"event": name, "log_error": True}))


@contextmanager
def timed(name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        observe(name, time.perf_counter() - started)


def metrics() -> dict:
    total = _counters["tool_success"] + _counters["tool_failure"]
    lat = sorted(_latencies)
    return {
        "counters": dict(_counters),
        "critical": {k: _counters[k] for k in CRITICAL},
        "tool_success_rate": round(_counters["tool_success"] / total, 3) if total else None,
        "tool_calls": total,
        "latency_ms": {
            "avg": round(sum(lat) / len(lat) * 1000, 1) if lat else None,
            "p95": round(lat[int(len(lat) * 0.95) - 1] * 1000, 1) if lat else None,
            "samples": len(lat),
        },
    }
