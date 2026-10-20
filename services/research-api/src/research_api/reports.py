"""Mode-specific, bounded reports composed only from evidence-gated findings."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field


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
        return {"focused": 4096, "balanced": 6144, "deep": 16384}[self.mode]


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
class ReportFigure:
    """A reported figure whose value is copied verbatim from a verified quote."""

    subject: str
    metric: str
    value: str
    source_number: int


@dataclass(frozen=True)
class ReportFinding:
    text: str
    source_numbers: tuple[int, ...]
    section: str = "mechanisms"
    figures: tuple[ReportFigure, ...] = field(default=())

    def cited(self) -> str:
        return self.text + " " + " ".join(f"[{n}]" for n in dict.fromkeys(self.source_numbers))


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]$|<>#~])")
FIGURE_TABLE_LIMITS = {"focused": 2, "balanced": 4, "deep": 6}
FIGURE_TABLE_MAX_ROWS = 24


def _clean(text: str) -> str:
    return " ".join(text.split())


def _literal(haystack: str, needle: str, *, keep_percent: bool = False) -> bool:
    """Whole-token literal match: "4.5" never matches inside "14.5" or "4.55"."""
    pattern = r"(?<![\w.,])" + re.escape(needle) + (r"(?![\w])" if needle[-1].isalnum() else "")
    if needle[-1].isdigit():
        pattern += r"(?![.,]?\d)"
        if keep_percent:
            # A copied value must not drop the percent sign that follows it in the quote.
            pattern += r"(?!\s?[%\u2030])"
    return re.search(pattern, haystack) is not None


def verified_figures(
    claim: str,
    proposals: Sequence[object],
    citations: Sequence[tuple[int, str]],
) -> tuple[ReportFigure, ...]:
    """Keep only figures whose value and labels are literally present in the evidence.

    `citations` must be the claim's exact-span-verified (source_number, quote) pairs in
    proposal order. A figure survives only when its value appears verbatim in the cited
    quote, its number appears in the published claim, and both labels appear in the claim
    or the quote. Nothing here interprets, converts or normalizes a value.
    """
    kept: list[ReportFigure] = []
    for proposal in proposals:
        index = getattr(proposal, "citation_index", None)
        if not isinstance(index, int) or not 0 <= index < len(citations):
            continue
        source_number, quote = citations[index]
        value = _clean(str(getattr(proposal, "value", "")))
        subject = _clean(str(getattr(proposal, "subject", "")))
        metric = _clean(str(getattr(proposal, "metric", "")))
        number = _NUMBER.search(value)
        if not (value and subject and metric and number) or len(value) > 40:
            continue
        if not _literal(_clean(quote), value, keep_percent=True):
            continue
        if not _literal(claim, number.group()):
            continue
        evidence = (_clean(claim) + "\n" + _clean(quote)).casefold()
        if subject.casefold() not in evidence or metric.casefold() not in evidence:
            continue
        figure = ReportFigure(subject, metric, value, source_number)
        if figure not in kept:
            kept.append(figure)
    return tuple(kept)


def _cell(text: str, limit: int = 120) -> str:
    text = _clean(text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "\u2026"
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _placement(
    policy: ReportPolicy, findings: list[ReportFinding]
) -> tuple[list[ReportFinding], list[tuple[str, list[ReportFinding]]]]:
    overview = [item for item in findings if item.section == "overview"]
    # Summarize with existing verified text, not a new unchecked model paraphrase.
    if not overview:
        overview = findings[:2]
    remaining = [item for item in findings if item not in overview]
    known = {"overview", *dict(policy.sections)}
    placed = [
        (
            title,
            [
                item
                for item in remaining
                if item.section == key or (key == "mechanisms" and item.section not in known)
            ],
        )
        for key, title in policy.sections
    ]
    return overview, placed


def _figure_tables(policy: ReportPolicy, findings: list[ReportFinding]) -> list[str]:
    """One table per metric so a chart never compares different measures."""
    groups: dict[str, list[ReportFigure]] = {}
    for finding in findings:
        for figure in finding.figures:
            rows = groups.setdefault(figure.metric.casefold(), [])
            if figure not in rows:
                rows.append(figure)
    tables = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows = rows[:FIGURE_TABLE_MAX_ROWS]
        metric = _cell(rows[0].metric[:1].upper() + rows[0].metric[1:], 80)
        tables.append(
            f"### {metric}\n\n"
            + _table(
                ("Subject", metric, "Source"),
                [
                    (_cell(row.subject), _cell(row.value, 40), f"[{row.source_number}]")
                    for row in rows
                ],
            )
        )
        if len(tables) == FIGURE_TABLE_LIMITS[policy.mode]:
            break
    return tables


def _source_table(
    summary: list[ReportFinding],
    placed: list[tuple[str, list[ReportFinding]]],
    sources: list[tuple[str, str]],
) -> str | None:
    sections: dict[int, list[str]] = {}
    counts: dict[int, int] = {}
    shared: dict[int, int] = {}
    for title, items in [("Executive summary", summary), *placed]:
        for item in items:
            numbers = [n for n in dict.fromkeys(item.source_numbers) if 1 <= n <= len(sources)]
            for number in numbers:
                counts[number] = counts.get(number, 0) + 1
                shared[number] = shared.get(number, 0) + (len(numbers) > 1)
                if title not in sections.setdefault(number, []):
                    sections[number].append(title)
    if len(counts) < 2:
        return None
    rows = [
        (
            f"{_cell(sources[number - 1][0] or 'Untitled source', 90)} [{number}]",
            str(counts[number]),
            str(shared[number]),
            _cell("; ".join(sections[number]), 160),
        )
        for number in sorted(counts)
    ]
    return _table(("Source", "Findings", "Shared findings", "Sections"), rows)


def render_report(
    policy: ReportPolicy,
    findings: list[ReportFinding],
    sources: list[tuple[str, str]],
    excluded: int,
) -> str:
    if not findings:
        parts = [
            "## Research finished—answer not established",
            (
                "No findings passed the evidence checks. The collected sources do not yet "
                "establish an answer to this question."
            ),
            "## Limitations",
            (
                f"Reviewed {len(sources)} source extracts; {excluded} candidate assertions "
                "were excluded. Review the recorded checks and research gaps to choose "
                "a narrower follow-up question. Collected sources remain available for inspection."
            ),
        ]
        if sources:
            parts += [
                "## Sources",
                "\n".join(f"{i}. [{title}]({url})" for i, (title, url) in enumerate(sources, 1)),
            ]
        return "\n\n".join(parts) + "\n"
    overview, placed = _placement(policy, findings)
    parts = [
        "## Executive summary",
        "\n\n".join(item.cited() for item in overview),
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
    for title, selected in placed:
        if selected:
            parts += [f"## {title}", "\n\n".join(item.cited() for item in selected)]
    figure_tables = _figure_tables(policy, findings)
    if figure_tables:
        parts += [
            "## Key figures",
            (
                "Each value is copied verbatim from a verified source passage. Values from "
                "different sources may use different definitions, samples or periods, so "
                "compare them with care."
            ),
            *figure_tables,
        ]
    source_table = _source_table(overview, placed, sources) if policy.mode != "focused" else None
    if source_table:
        parts += [
            "## Evidence by source",
            (
                "How the published findings draw on each cited source. Shared findings also "
                "cite another source; this shows overlap, not publisher independence."
            ),
            source_table,
        ]
    if policy.mode == "deep" and findings:
        coverage = [
            (
                _cell(title),
                str(len(items)),
                str(len({n for item in items for n in item.source_numbers})),
            )
            for title, items in [("Executive summary", overview), *placed]
        ]
        parts += [
            "## Evidence coverage",
            "Published findings and distinct cited sources in each section of this report.",
            _table(("Section", "Findings", "Cited sources"), coverage),
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
    ]
    parts += [
        "## Sources",
        "\n".join(f"{i}. [{title}]({url})" for i, (title, url) in enumerate(sources, 1)),
    ]
    return "\n\n".join(parts) + "\n"
