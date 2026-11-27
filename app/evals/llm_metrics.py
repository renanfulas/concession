"""Deterministic answer checks for the opt-in real-LLM eval mode.

These checks look only at the generated text and the retrieved references, so
they are reproducible given the same answer. They never call a model.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.text import fold

# A number followed by a time unit, on folded text ("24 horas", "4h", "15 dias",
# "30 min"). Rates such as "24 horas por dia" or "7 dias por semana" describe
# coverage, not a deadline, and are ignored. Numbers written as words ("quatro
# horas") are not detected.
_DURATION = re.compile(
    r"(?<![\d.,])(\d+)\s*(horas?|hrs?|h|dias?|minutos?|min)(?![a-z])"
    r"(?!\s+por\s+(?:dia|semana|mes)\b)"
)

_UNIT_CANONICAL = {
    "h": "horas",
    "hr": "horas",
    "hrs": "horas",
    "hora": "horas",
    "horas": "horas",
    "dia": "dias",
    "dias": "dias",
    "min": "minutos",
    "minuto": "minutos",
    "minutos": "minutos",
}

Duration = tuple[int, str]


def _canonical(match: re.Match[str]) -> Duration:
    return int(match.group(1)), _UNIT_CANONICAL[match.group(2)]


def extract_durations(text: str) -> list[Duration]:
    """Return every duration in ``text`` as ``(value, canonical_unit)``, in order."""
    return [_canonical(match) for match in _DURATION.finditer(fold(text))]


def parse_duration(value: str) -> Duration | None:
    """Parse a single duration such as "24 horas" or "24h"; None if invalid."""
    match = _DURATION.fullmatch(fold(value).strip())
    if match is None:
        return None
    return _canonical(match)


def format_duration(duration: Duration) -> str:
    value, unit = duration
    return f"{value} {unit}"


def evaluate_llm_expectation(
    expectation: Any,
    *,
    answer: str,
    references: list[str],
) -> dict[str, list[str]]:
    """Apply an ``LLMExpectation`` to one answer.

    Returns ``{metric: failures}`` for every metric the expectation configures;
    an empty failure list means the metric passed.
    """
    folded = fold(answer)
    metrics: dict[str, list[str]] = {}

    if expectation.any_of:
        metrics["any_of"] = [
            "missing_any_of:" + "|".join(group)
            for group in expectation.any_of
            if not any(fold(term) in folded for term in group)
        ]

    if expectation.forbidden_terms:
        metrics["llm_forbidden_terms"] = [
            f"forbidden_term_present:{term}"
            for term in expectation.forbidden_terms
            if fold(term) in folded
        ]

    if expectation.allowed_durations:
        allowed = {parse_duration(value) for value in expectation.allowed_durations}
        failures: list[str] = []
        for duration in extract_durations(answer):
            failure = f"disallowed_duration:{format_duration(duration)}"
            if duration not in allowed and failure not in failures:
                failures.append(failure)
        metrics["allowed_durations"] = failures

    if expectation.expected_citation:
        failures = []
        for citation in expectation.expected_citation:
            if re.search(citation.pattern, folded, re.IGNORECASE) is None:
                failures.append(f"missing_citation:{citation.pattern}")
            if not any(citation.source in reference for reference in references):
                failures.append(f"citation_source_not_retrieved:{citation.source}")
        metrics["expected_citation"] = failures

    return metrics
