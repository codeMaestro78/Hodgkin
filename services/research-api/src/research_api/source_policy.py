"""Deterministic source constraints for explicitly requested official docs."""

import re
from collections.abc import Mapping
from typing import Any

# Keep this allowlist explicit: a product name is not enough to safely infer its
# canonical documentation host. Add entries only when the official host is known.
OFFICIAL_DOCUMENTATION_DOMAINS = {
    "langgraph": ("docs.langchain.com",),
    "langchain": ("docs.langchain.com",),
}

_OFFICIAL_DOCS_REQUEST = re.compile(
    r"\bofficial\b.{0,80}\b(?:documentation|docs)\b|"
    r"\b(?:documentation|docs)\b.{0,80}\bofficial\b",
    re.IGNORECASE,
)


def official_documentation_domains(question: str) -> list[str]:
    """Return known hosts only for an explicit official-docs request."""
    if not _OFFICIAL_DOCS_REQUEST.search(question):
        return []
    lowered = question.casefold()
    matched = {
        domain
        for product, domains in OFFICIAL_DOCUMENTATION_DOMAINS.items()
        if re.search(rf"\b{re.escape(product)}\b", lowered)
        for domain in domains
    }
    return sorted(matched)


def allowed_domains_from_plan(plan: Mapping[str, Any]) -> list[str]:
    """Load only known domains from the durable plan-level source policy."""
    policy = plan.get("source_policy")
    if not isinstance(policy, Mapping) or policy.get("kind") != "official_documentation":
        return []
    requested = policy.get("allowed_domains")
    if not isinstance(requested, list) or any(not isinstance(item, str) for item in requested):
        return []
    known = {domain for domains in OFFICIAL_DOCUMENTATION_DOMAINS.values() for domain in domains}
    return sorted(set(requested) & known)


def query_with_domain_hints(query: str, domains: list[str] | None) -> str:
    """Bias search ranking toward the same hosts that are enforced as filters."""
    if not domains:
        return query
    unique_domains = sorted(set(domains))
    if all(f"site:{domain}" in query.casefold() for domain in unique_domains):
        return query
    suffix = " ".join(f"site:{domain}" for domain in unique_domains)
    if len(suffix) >= 1000:
        raise ValueError("official source-domain policy exceeds query limit")
    bounded_query = query[: 999 - len(suffix)].rstrip()
    return f"{bounded_query} {suffix}"
