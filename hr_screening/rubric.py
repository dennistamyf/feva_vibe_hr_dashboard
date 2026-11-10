"""Parse the approved scoring template into criteria, weights, and tie-break."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InputValidationError

_CRITERION_RE = re.compile(
    r"^\s*[-*]\s*(?P<name>[^:]+?)\s*:\s*"
    r"(?P<weight>\d+(?:\.\d+)?)\s*%\s*[.\-:]?\s*"
    r"(?P<guidance>.*)$"
)
_TIE_BREAK_RE = re.compile(
    r"Resolve equal scores by preferring the candidate with more direct evidence of "
    r"(?P<primary>.+?),\s*then the candidate with more recent relevant experience\.",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Criterion:
    name: str
    weight: float
    guidance: str


@dataclass(frozen=True)
class Rubric:
    criteria: tuple[Criterion, ...]
    tie_break_primary: str
    raw_text: str

    @property
    def criterion_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.criteria)

    @property
    def weight_total(self) -> float:
        return sum(c.weight for c in self.criteria)


def parse_rubric(scoring_template: str, source_name: str = "scoring template") -> Rubric:
    criteria: list[Criterion] = []
    seen: set[str] = set()

    for line in scoring_template.splitlines():
        match = _CRITERION_RE.match(line)
        if not match:
            continue
        name = re.sub(r"\s+", " ", match.group("name")).strip()
        guidance = re.sub(r"\s+", " ", match.group("guidance")).strip()
        weight = float(match.group("weight"))
        key = name.casefold()
        if key in seen:
            raise InputValidationError(
                f"Duplicate rubric criterion in {source_name}: {name}"
            )
        if not name:
            raise InputValidationError(
                f"An empty rubric criterion name was found in {source_name}."
            )
        if not guidance:
            raise InputValidationError(
                f"Rubric criterion '{name}' has no scoring guidance in {source_name}."
            )
        if weight <= 0 or weight > 100:
            raise InputValidationError(
                f"Rubric criterion '{name}' has an invalid weight ({weight}%) "
                f"in {source_name}."
            )
        seen.add(key)
        criteria.append(Criterion(name=name, weight=weight, guidance=guidance))

    if not criteria:
        raise InputValidationError(
            f"No weighted rubric criteria were found in {source_name}. "
            "Expected bullet lines such as '- Criterion: 25%. Guidance'."
        )

    total = sum(c.weight for c in criteria)
    if abs(total - 100.0) > 0.01:
        raise InputValidationError(
            f"Rubric weights in {source_name} must total 100%; found {total:g}%."
        )

    flat = re.sub(r"\s+", " ", scoring_template).strip()
    tie_match = _TIE_BREAK_RE.search(flat)
    primary = (
        re.sub(r"\s+", " ", tie_match.group("primary")).strip()
        if tie_match
        else "direct ownership evidence relevant to the role"
    )
    if not primary:
        primary = "direct ownership evidence relevant to the role"

    return Rubric(
        criteria=tuple(criteria),
        tie_break_primary=primary,
        raw_text=scoring_template,
    )
