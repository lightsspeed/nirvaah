"""Model providers for the assistant.

Primary: a local Ollama model (nothing leaves the machine).
Fallback: any OpenAI-compatible chat-completions endpoint (DeepSeek through
AgentRouter, OpenAI, Groq, …) used when the local model is unreachable or
answers with something the action parser cannot read.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "180"))
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))

FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", "https://agentrouter.org/v1").rstrip("/")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "deepseek-v4-flash")
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY", "")
FALLBACK_TIMEOUT = float(os.getenv("FALLBACK_TIMEOUT", "120"))
# on | off — lets a deployment run local-only even when a key is present.
FALLBACK_MODE = os.getenv("ASSISTANT_FALLBACK", "on").strip().lower()


class ProviderError(RuntimeError):
    """The provider could not be reached or returned an unusable answer."""


@dataclass
class Reply:
    text: str
    provider: str  # "local" | "cloud"
    model: str
    degraded: str = ""  # technical: why the primary was skipped/failed
    note: str = ""      # one friendly sentence for the transcript



def _as_json_object(text: str) -> str:
    """Providers that ignore json mode answer in prose. Wrap it instead of
    throwing a perfectly good answer away and dropping to a weaker model."""
    stripped = text.strip()
    try:
        if isinstance(json.loads(stripped), dict):
            return stripped
    except (ValueError, TypeError):
        pass
    return json.dumps({"reply": stripped, "actions": []})


def _post(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:200]
        raise ProviderError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ProviderError(f"{url} timed out after {timeout:.0f}s") from exc


def call_local(messages: list[dict], model: str | None = None) -> Reply:
    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": NUM_CTX},
    }
    data = _post(f"{OLLAMA_URL}/api/chat", payload, OLLAMA_TIMEOUT)
    text = ((data.get("message") or {}).get("content") or "").strip()
    if not text:
        raise ProviderError("local model returned an empty message")
    return Reply(text=_as_json_object(text), provider="local", model=model or OLLAMA_MODEL)


def call_fallback(messages: list[dict], model: str | None = None) -> Reply:
    if not FALLBACK_API_KEY:
        raise ProviderError("no FALLBACK_API_KEY configured")
    payload = {
        "model": model or FALLBACK_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {FALLBACK_API_KEY}"}
    data = _post(f"{FALLBACK_BASE_URL}/chat/completions", payload, FALLBACK_TIMEOUT, headers=headers)
    choices = data.get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not text:
        # Some endpoints answer empty when a JSON response_format is requested;
        # one retry without it is cheaper than dropping to the local model.
        retry = {k: v for k, v in payload.items() if k != "response_format"}
        data = _post(f"{FALLBACK_BASE_URL}/chat/completions", retry, FALLBACK_TIMEOUT, headers=headers)
        choices = data.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not text:
        finish = (choices[0].get("finish_reason") if choices else "no choices") or "no content"
        raise ProviderError(f"fallback model returned an empty message ({finish})")
    return Reply(text=_as_json_object(text), provider="cloud", model=model or FALLBACK_MODEL)


def fallback_ready() -> bool:
    return bool(FALLBACK_API_KEY) and FALLBACK_MODE != "off"


def _plan(prefer: str) -> list[tuple[str, str | None]]:
    """The assistant runs on one model: deepseek-flash.

    An earlier build let the user pick between the local Ollama model, flash and
    v4-pro; one model keeps every answer consistent, and the cloud model is the
    only one that gets the figures right (a 3B sums the wrong rows). `prefer` is
    still accepted from older clients and ignored.
    """
    return [("cloud", FALLBACK_MODEL)]


def _short_reason(exc: Exception) -> str:
    text = str(exc).lower()
    if "empty message" in text:
        return "returned an empty answer"
    if "cannot reach" in text or "connection refused" in text:
        return "was unreachable"
    if "timed out" in text:
        return "timed out"
    if "json" in text:
        return "returned an unusable answer"
    if "no fallback_api_key" in text or "not configured" in text:
        return "is not configured"
    return "failed"


def ask(messages: list[dict], validate=None, prefer: str = "") -> Reply:
    """Run the provider chain. `validate` raises ValueError on unusable output."""
    problems: list[tuple[str, str]] = []  # (name, reason)

    for label, model in _plan(prefer):
        name = model or (OLLAMA_MODEL if label == "local" else FALLBACK_MODEL)
        if label == "cloud" and not fallback_ready():
            problems.append((name, "is not configured"))
            continue
        caller = call_local if label == "local" else call_fallback
        try:
            reply = caller(messages, model)
            if validate is not None:
                validate(reply.text)  # raises ValueError when unparseable
            reply.degraded = "; ".join(f"{n}: {r}" for n, r in problems)
            if problems:
                failed, reason = problems[0]
                answerer = "the local model" if reply.provider == "local" else reply.model
                reply.note = f"{failed} {reason} — answered by {answerer} instead."
            return reply
        except (ProviderError, ValueError) as exc:
            problems.append((f"{name}" if label == "cloud" else f"{name}", _short_reason(exc)))
            continue

    detail = " | ".join(f"{n}: {r}" for n, r in problems)
    raise ProviderError("no model could answer — " + detail)


_CLOUD_CACHE: dict = {"at": 0.0, "models": [], "error": ""}


def cloud_models(force: bool = False) -> tuple[list[str], str]:
    """The model ids the cloud endpoint exposes (cached for two minutes)."""
    if not FALLBACK_API_KEY:
        return [], "no FALLBACK_API_KEY configured"
    now = time.time()
    if not force and now - _CLOUD_CACHE["at"] < 120:
        return _CLOUD_CACHE["models"], _CLOUD_CACHE["error"]
    request = urllib.request.Request(
        f"{FALLBACK_BASE_URL}/models",
        headers={"Authorization": f"Bearer {FALLBACK_API_KEY}"},
    )
    models: list[str] = []
    error = ""
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [m.get("id") for m in payload.get("data", []) if m.get("id")]
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    _CLOUD_CACHE.update(at=now, models=models, error=error)
    return models, error


def status() -> dict:
    local = {"url": OLLAMA_URL, "model": OLLAMA_MODEL, "reachable": False, "models": [], "error": ""}
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as response:
            names = [m.get("name") for m in json.loads(response.read().decode("utf-8")).get("models", [])]
        local.update(reachable=True, models=names)
    except Exception as exc:  # noqa: BLE001
        local["error"] = str(exc)

    cloud_list, cloud_error = cloud_models()
    cloud = {
        "enabled": fallback_ready(),
        "base_url": FALLBACK_BASE_URL,
        "model": FALLBACK_MODEL,
        "models": cloud_list,
        "reachable": bool(cloud_list),
        "error": cloud_error,
        "key_present": bool(FALLBACK_API_KEY),
    }
    # One flat list the UI renders directly: local models first, then cloud.
    models = [
        {"id": f"local:{name}", "name": name, "provider": "local", "active": name == OLLAMA_MODEL}
        for name in local["models"]
    ] + [
        {"id": f"cloud:{name}", "name": name, "provider": "cloud", "active": name == FALLBACK_MODEL}
        for name in cloud_list
    ]
    return {
        "local": local,
        "fallback": cloud,
        "models": models,
        "available": local["reachable"] or cloud["reachable"],
        "model": OLLAMA_MODEL if local["reachable"] else FALLBACK_MODEL,
    }
