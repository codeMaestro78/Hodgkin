"""Pure DOI identity normalization for discovery metadata."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

MAX_DOI_CHARS = 2048
_DOI = re.compile(r"10\.[0-9]{4,9}/[^\s]+\Z", re.IGNORECASE)
_RESOLVERS = frozenset({"doi.org", "dx.doi.org"})


def normalize_doi(value: object) -> str | None:
    """Return a lowercase DOI or None; this performs no network resolution.

    Accept bare DOIs, ``doi:`` labels, and DOI resolver URLs. Do not trim DOI
    punctuation: punctuation can be part of a registered suffix.
    """
    if not isinstance(value, str):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    raw = value.strip()
    if raw.lower().startswith("doi:"):
        raw = raw[4:].strip()
    elif "://" in raw:
        try:
            parsed = urlsplit(raw)
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or parsed.hostname is None
                or parsed.hostname.lower() not in _RESOLVERS
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port is not None
                or parsed.query
                or parsed.fragment
            ):
                return None
            raw = unquote(parsed.path.lstrip("/"))
        except ValueError:
            return None
    if not 1 <= len(raw) <= MAX_DOI_CHARS or _DOI.fullmatch(raw) is None:
        return None
    if any(ord(char) < 33 or ord(char) > 126 for char in raw):
        return None
    # Preserve path identity when this DOI is later appended to an API URL.
    if any(segment in {".", ".."} for segment in raw.split("/")):
        return None
    return raw.lower()
