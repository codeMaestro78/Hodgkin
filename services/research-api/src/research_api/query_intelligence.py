from __future__ import annotations

import re

_QUICK_EXPLAINER = re.compile(r"^(what is|who is|define|explain)\s+.+\??$", re.IGNORECASE)
_TIME_SENSITIVE_TERMS = re.compile(
    r"\b(latest|current|today|recent|news|202[0-9]|202[0-9]s|price|stock|law|policy)\b",
    re.IGNORECASE,
)


def is_quick_explainer(question: str) -> bool:
    """Route simple evergreen definitions to a compact evidence pass."""
    normalized = " ".join(question.split())
    return (
        len(normalized) <= 160
        and bool(_QUICK_EXPLAINER.match(normalized))
        and not bool(_TIME_SENSITIVE_TERMS.search(normalized))
    )
