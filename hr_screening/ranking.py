"""Rank validated evaluations only after the full batch is complete."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InputValidationError
from .models import Evaluation
from .rubric import Rubric


@dataclass(frozen=True)
class RankedCandidate:
    evaluation: Evaluation
    rank: int


@dataclass(frozen=True)
class RankingResult:
    ranked: tuple[RankedCandidate, ...]
    selected: tuple[RankedCandidate, ...]
    tie_break_notes: tuple[str, ...]


def _recency_label(evaluation: Evaluation) -> str:
    tie = evaluation.tie_break
    if tie.most_recent_relevant_is_current:
        return "current"
    if tie.most_recent_relevant_end_year is not None:
        return str(tie.most_recent_relevant_end_year)
    return "no documented year"


def _tie_note(group: list[Evaluation], score: float, rubric: Rubric) -> str:
    ordered = sorted(
        group,
        key=lambda item: (
            -item.tie_break.primary_evidence_level,
            -item.tie_break.recency_key,
            item.source_pdf_filename.casefold(),
        ),
    )
    details = []
    for item in ordered:
        details.append(
            f"{item.full_name} (primary evidence level "
            f"{item.tie_break.primary_evidence_level}, most recent relevant "
            f"experience: {_recency_label(item)})"
        )
    note = (
        f"Tie at {score:.1f}: the rubric tie-break was used, preferring more "
        f"direct evidence of {rubric.tie_break_primary}, then more recent "
        f"relevant experience. Order after tie-break: " + "; ".join(details) + "."
    )
    unresolved = any(
        first.tie_break.primary_evidence_level
        == second.tie_break.primary_evidence_level
        and first.tie_break.recency_key == second.tie_break.recency_key
        for first, second in zip(ordered, ordered[1:])
    )
    if unresolved:
        note += (
            " At least one adjacent pair remained tied after both criteria; "
            "source filename order is used for display only."
        )
    return note


def rank_and_select(
    evaluations: list[Evaluation] | tuple[Evaluation, ...],
    rubric: Rubric,
    top_n: int,
) -> RankingResult:
    if not evaluations:
        raise InputValidationError(
            "Cannot rank an empty candidate set. The run was stopped."
        )
    if top_n < 1 or top_n > len(evaluations):
        raise InputValidationError(
            f"Cannot select {top_n} candidates from {len(evaluations)} evaluations."
        )

    by_score: dict[float, list[Evaluation]] = {}
    for evaluation in evaluations:
        by_score.setdefault(evaluation.weighted_score, []).append(evaluation)

    notes: list[str] = []
    ordered: list[Evaluation] = []
    for score in sorted(by_score, reverse=True):
        group = by_score[score]
        if len(group) > 1:
            notes.append(_tie_note(group, score, rubric))
            group = sorted(
                group,
                key=lambda item: (
                    -item.tie_break.primary_evidence_level,
                    -item.tie_break.recency_key,
                    item.source_pdf_filename.casefold(),
                ),
            )
        else:
            group = list(group)
        ordered.extend(group)

    ranked = tuple(
        RankedCandidate(evaluation=evaluation, rank=index)
        for index, evaluation in enumerate(ordered, start=1)
    )
    return RankingResult(
        ranked=ranked,
        selected=ranked[:top_n],
        tie_break_notes=tuple(notes),
    )
