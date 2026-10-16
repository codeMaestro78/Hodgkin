"""Mode-specific, bounded reports composed only from evidence-gated findings."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReportPolicy:
    mode: str
    source_count: int
    candidate_count: int
    context_chars: int
    sections: tuple[tuple[str, str], ...]

    @property
    def question_count(self) -> int:
        return {"focused": 3, "balanced": 4, "deep": 6}[self.mode]

    @property
    def output_tokens(self) -> int:
        return {"focused": 4096, "balanced": 6144, "deep": 8192}[self.mode]


def report_policy(calls: int) -> ReportPolicy:
    if calls <= 6:
        return ReportPolicy(
            "focused",
            min(calls, 6),
            12,
            12_000,
            (
                ("mechanisms", "Analysis"),
                ("comparison", "Comparison"),
                ("risks", "Trade-offs"),
                ("implications", "Implications"),
            ),
        )
    if calls <= 12:
        return ReportPolicy(
            "balanced",
            min(calls, 12),
            24,
            18_000,
            (
                ("mechanisms", "How the approaches work"),
                ("comparison", "Comparative analysis"),
                ("risks", "Risks and operational trade-offs"),
                ("implications", "Decision implications"),
            ),
        )
    return ReportPolicy(
        "deep",
        min(calls, 20),
        40,
        24_000,
        (
            ("mechanisms", "Detailed mechanisms and architecture"),
            ("comparison", "Cross-source comparative analysis"),
            ("risks", "Failure modes, constraints and trade-offs"),
            ("implications", "Implementation and decision implications"),
        ),
    )


def select_passages(content: str, question: str, limit: int) -> str:
    """Rank overlapping literal slices; never paraphrase or normalize source quotes."""
    terms = set(re.findall(r"\w{4,}", question.lower()))
    windows = [(start, content[start : start + 1000]) for start in range(0, len(content), 800)]
    ranked = sorted(
        windows,
        key=lambda item: (-len(terms & set(re.findall(r"\w{4,}", item[1].lower()))), item[0]),
    )
    selected: list[tuple[int, str]] = []
    used = 0
    for start, passage in ranked:
        if any(abs(start - old) < 1000 for old, _ in selected):
            continue
        room = limit - used - (len("\n[separate passage]\n") if selected else 0)
        if room <= 0:
            break
        passage = passage[:room]
        selected.append((start, passage))
        used += len(passage) + (len("\n[separate passage]\n") if len(selected) > 1 else 0)
    return "\n[separate passage]\n".join(passage for _, passage in sorted(selected))


@dataclass(frozen=True)
class ReportFinding:
    text: str
    source_numbers: tuple[int, ...]
    section: str = "mechanisms"

    def cited(self) -> str:
        return self.text + " " + " ".join(f"[{n}]" for n in dict.fromkeys(self.source_numbers))


def render_report(
    policy: ReportPolicy,
    findings: list[ReportFinding],
    sources: list[tuple[str, str]],
    excluded: int,
) -> str:
    overview = [item for item in findings if item.section == "overview"]
    # Summarize with existing verified text, not a new unchecked model paraphrase.
    if not overview:
        overview = findings[:2]
    remaining = [item for item in findings if item not in overview]
    parts = [
        "## Executive summary",
        "\n\n".join(item.cited() for item in overview)
        or (
            "No factual findings were published: no draft assertion met the full evidence gate. "
            "This is a limited evidence record, not an answered research question."
        ),
    ]
    if policy.mode == "deep":
        parts += [
            "## Scope and evidence boundaries",
            (
                "The sections below distinguish supported findings from unresolved evidence. "
                "Coverage is limited to collected extracts; "
                "missing evidence is not proof of absence."
            ),
        ]
    for key, title in policy.sections:
        selected = [
            item
            for item in remaining
            if item.section == key
            or (
                key == "mechanisms"
                and item.section not in {"overview", "comparison", "risks", "implications"}
            )
        ]
        parts += [
            f"## {title}",
            "\n\n".join(item.cited() for item in selected)
            or (
                "This section is incomplete: no additional supported finding was established. "
                "Inspect the research gaps before drawing a conclusion."
            ),
        ]
    parts += [
        "## Limitations",
        (
            f"{excluded} candidate assertions were excluded by the evidence gate. "
            "Only exact passages with fully supportive semantic reviews are published. "
            "Model extraction is not exhaustive and model review is not factual certification. "
            "Unpublished assertions and coverage gaps remain inspectable in Checks."
        ),
        "## Methodology",
        (
            f"Mode: {policy.mode.capitalize()}. Reviewed {len(sources)} exact-content-deduplicated "
            f"source extracts; published {len(findings)} verified findings. "
            "Passages were selected for question relevance, then exact quotation and semantic "
            "support were checked. Content deduplication does not establish publisher independence."
        ),
        "## Sources",
        "\n".join(f"{i}. [{title}]({url})" for i, (title, url) in enumerate(sources, 1)),
    ]
    return "\n\n".join(parts) + "\n"
