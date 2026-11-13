"""Credentials never become long-term memory.

A stored fact is replayed into every later prompt, so a password or token in a
memory would be sent to the model provider on every turn. This module answers
one deterministic question — does this text *declare* a credential? — and the
memory writers refuse when it does.

Two layers, both narrow:

* known key formats (``AKIA…``, ``sk-…``, ``ghp_…``, ``Bearer …``, private keys);
* a credential noun followed, after at most three filler words, by a linking
  verb and a value — "my wifi password is hunter2".

Deliberately absent: high-entropy detection. It would flag git SHAs, UUIDs,
hashes and long account numbers, which are not credentials. The guard is a
floor, not a DLP system.
"""

from __future__ import annotations

import re


# Unambiguous key formats — no surrounding words needed.
_FORMATS: tuple[tuple[str, re.Pattern], ...] = (
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("an API key", re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")),
    ("an access token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}\b")),
    ("an access token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an access token", re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I)),
)

# Credential nouns. Bare "code" is excluded on purpose: an error code, a zip
# code or a source-code review is not a credential.
_NOUN = (
    r"(?:passwords?|passphrases?|passwd|pwd|pins?|pin[\s-]?codes?|passcodes?|"
    r"api[\s-]?keys?|access[\s-]?keys?|secret[\s-]?keys?|private[\s-]?keys?|"
    r"access[\s-]?tokens?|bearer[\s-]?tokens?|auth(?:entication)?[\s-]?tokens?|"
    r"tokens?|secrets?|credentials?|"
    r"access[\s-]?codes?|locker[\s-]?codes?|door[\s-]?codes?|gate[\s-]?codes?|"
    r"security[\s-]?codes?|seed[\s-]?phrases?|recovery[\s-]?(?:codes?|phrases?)|"
    r"one[\s-]?time[\s-]?(?:codes?|passwords?)|otps?)"
)

# "…for the wifi is…", "…of my account is…". The gap takes up to four words but
# stops at words that make the sentence a topic rather than a declaration, so
# "token bucket is", "password manager is", "secret sauce is" stay harmless.
_SAFE_TOPIC = (
    r"(?:bucket|manager|polic(?:y|ies)|reset|strength|field|hint|requirement|requirements|"
    r"rules?|regex|validation|expiry|expiration|length|change|rotation|generator|vault|"
    r"headers?|names?|format|scheme|type|sauce|recipe|ingredient|prompt|story)"
)
_GAP = rf"(?:\s+(?!{_SAFE_TOPIC}\b)\S+){{0,4}}"
# "the password is correct" states a property; "…is correct horse battery staple"
# is a value that merely starts with that word.
_SAFE_VALUE = (
    r"(?!(?:required|needed|optional|missing|wrong|correct|incorrect|strong|weak|hidden|"
    r"encrypted|rotated|changed|forgotten|set|unset|case)\b[.!?,;]?\s*$)"
)

_DECLARED = re.compile(
    rf"\b(?P<noun>{_NOUN})\b{_GAP}\s*(?:is|are|was|were|will be|should be|becomes?|:|=)\s*"
    rf"{_SAFE_VALUE}\S",
    re.I,
)


def _label(noun: str) -> str:
    word = noun.lower()
    if "pin" in word or "passcode" in word:
        return "a PIN"
    if "pass" in word:
        return "a password"
    if "key" in word:
        return "an API key" if "api" in word else "a key"
    if "token" in word:
        return "an access token"
    if "secret" in word:
        return "a secret"
    if "phrase" in word:
        return "a recovery phrase"
    if "credential" in word:
        return "credentials"
    if "code" in word:
        return "an access code"
    return "a credential"


def credential_kind(text: str) -> str | None:
    """The kind of credential this text declares, or None.

    Never returns, logs or formats the value itself.
    """
    body = (text or "").strip()
    if not body:
        return None
    for label, pattern in _FORMATS:
        if pattern.search(body):
            return label
    match = _DECLARED.search(body)
    if match:
        return _label(match.group("noun"))
    return None


def refusal(kind: str | None = None) -> str:
    """The reply for a refused memory write — names the kind, never the value."""
    thing = kind or "credentials"
    return (f"I can't store {thing} in long-term memory — memories are sent to the "
            f"model provider on every turn. Please keep it in a password manager "
            f"and tell me something else.")
