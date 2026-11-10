"""Typed evaluation and interview-question schemas plus strict validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import EvaluationValidationError
from .rubric import Rubric

Recommendation = Literal["Strong yes", "Yes", "Maybe", "No"]

StrictScore = Annotated[int, Field(strict=True, ge=0, le=5)]
StrictLevel = Annotated[int, Field(strict=True, ge=0, le=2)]

_SENTENCE_RE = re.compile(r"[.!?](?=\s+[A-Z0-9\"'\\(\[]|\s*$)")
_MISSING_EVIDENCE_RE = re.compile(
    r"^\s*(?:no|not)\b[^.]*\bevidence\b", re.IGNORECASE
)


def _non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value.strip()


class CriterionAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    criterion: str
    score: StrictScore
    evidence: str
    source: str
    evidence_missing: bool = False

    @field_validator("criterion", "evidence", "source")
    @classmethod
    def _fields_not_blank(cls, value: str, info) -> str:
        return _non_blank(value, info.field_name)


class TieBreakAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_evidence_level: StrictLevel
    primary_evidence: str
    most_recent_relevant_role: str
    most_recent_relevant_employer: str
    most_recent_relevant_end_year: int | None = None
    most_recent_relevant_is_current: bool = False

    @field_validator(
        "primary_evidence", "most_recent_relevant_role", "most_recent_relevant_employer"
    )
    @classmethod
    def _tie_fields_not_blank(cls, value: str, info) -> str:
        return _non_blank(value, info.field_name)

    @field_validator("most_recent_relevant_end_year")
    @classmethod
    def _valid_year(cls, value: int | None) -> int | None:
        if value is None:
            return None
        current = datetime.now().year
        if value < 1950 or value > current + 1:
            raise ValueError(f"end year must be between 1950 and {current + 1}")
        return value

    @property
    def recency_key(self) -> int:
        if self.most_recent_relevant_is_current:
            return 9999
        return self.most_recent_relevant_end_year or 0


class EvaluationPayload(BaseModel):
    """The JSON shape requested from the model, before app-side identity."""

    model_config = ConfigDict(extra="ignore")

    full_name: str
    headline: str
    criteria: list[CriterionAssessment] = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommendation: Recommendation
    recommendation_rationale: str
    tie_break: TieBreakAssessment

    @field_validator("full_name", "headline", "recommendation_rationale")
    @classmethod
    def _text_not_blank(cls, value: str, info) -> str:
        return _non_blank(value, info.field_name)


class InterviewQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    based_on: str

    @field_validator("question", "based_on")
    @classmethod
    def _not_blank(cls, value: str, info) -> str:
        return _non_blank(value, info.field_name)


class InterviewQuestionSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    questions: list[InterviewQuestion] = Field(min_length=1)


@dataclass(frozen=True)
class Evaluation:
    """Validated evaluation with app-owned identity and weighted score."""

    candidate_stem: str
    source_pdf_filename: str
    source_pdf_path: Path
    full_name: str
    headline: str
    criteria: tuple[CriterionAssessment, ...]
    strengths: tuple[str, ...]
    concerns: tuple[str, ...]
    missing_information: tuple[str, ...]
    recommendation: Recommendation
    recommendation_rationale: str
    tie_break: TieBreakAssessment
    weighted_score: float

    @property
    def identity_key(self) -> str:
        return _identity_key(self.full_name)


def _identity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _criterion_key(value: str) -> str:
    """Normalize harmless formatting differences such as '&' versus 'and'."""

    normalized = value.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _safe_validation_details(exc: ValidationError, limit: int = 6) -> str:
    parts: list[str] = []
    for error in exc.errors()[:limit]:
        loc = ".".join(str(item) for item in error.get("loc", ()))
        msg = str(error.get("msg", "invalid value"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    if len(exc.errors()) > limit:
        parts.append("additional validation errors omitted")
    return "; ".join(parts)


def count_sentences(text: str) -> int:
    return len(_SENTENCE_RE.findall(text.strip()))


def weighted_score(
    assessments: list[CriterionAssessment] | tuple[CriterionAssessment, ...],
    rubric: Rubric,
) -> float:
    by_name = {item.criterion: item for item in assessments}
    total = Decimal("0")
    for criterion in rubric.criteria:
        item = by_name.get(criterion.name)
        if item is None:
            raise EvaluationValidationError(
                f"Missing criterion while calculating the weighted score: {criterion.name}"
            )
        total += (
            Decimal(item.score) / Decimal("5") * Decimal(str(criterion.weight))
        )
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def validate_evaluation_payload(
    raw: dict,
    rubric: Rubric,
    candidate_stem: str,
    source_pdf_filename: str,
    source_pdf_path: Path,
) -> Evaluation:
    """Validate one model response against the selected rubric.

    Unknown extra fields are ignored. Missing criteria, duplicate criteria,
    unknown criteria, out-of-range scores, blank evidence, and invalid
    recommendations are errors. Nothing is repaired or invented.
    """

    try:
        payload = EvaluationPayload.model_validate(raw)
    except ValidationError as exc:
        raise EvaluationValidationError(
            f"Invalid evaluation for {candidate_stem}: {_safe_validation_details(exc)}"
        ) from exc

    expected = list(rubric.criterion_names)
    expected_keys = {_criterion_key(name): name for name in expected}
    received: dict[str, CriterionAssessment] = {}
    for item in payload.criteria:
        key = _criterion_key(item.criterion)
        if key not in expected_keys:
            raise EvaluationValidationError(
                f"Invalid evaluation for {candidate_stem}: unknown criterion "
                f"'{item.criterion}'. Expected exactly: {', '.join(expected)}."
            )
        canonical = expected_keys[key]
        if canonical in received:
            raise EvaluationValidationError(
                f"Invalid evaluation for {candidate_stem}: criterion "
                f"'{canonical}' appears more than once."
            )
        received[canonical] = item.model_copy(update={"criterion": canonical})

    missing = [name for name in expected if name not in received]
    if missing:
        raise EvaluationValidationError(
            f"Invalid evaluation for {candidate_stem}: missing criterion "
            f"score(s): {', '.join(missing)}."
        )
    if len(received) != len(expected):
        raise EvaluationValidationError(
            f"Invalid evaluation for {candidate_stem}: expected {len(expected)} "
            f"criteria, received {len(received)}."
        )

    ordered = tuple(received[name] for name in expected)
    any_missing_evidence = False
    for item in ordered:
        looks_missing = bool(_MISSING_EVIDENCE_RE.match(item.evidence))
        if item.evidence_missing or looks_missing:
            any_missing_evidence = True
            if item.score != 0:
                raise EvaluationValidationError(
                    f"Invalid evaluation for {candidate_stem}: criterion "
                    f"'{item.criterion}' has a positive score but records missing "
                    "evidence. A score above 0 requires documented CV evidence."
                )
        if item.score > 0 and looks_missing:
            raise EvaluationValidationError(
                f"Invalid evaluation for {candidate_stem}: criterion "
                f"'{item.criterion}' has a positive score but its evidence says no "
                "evidence was found."
            )

    if any_missing_evidence and not payload.missing_information:
        raise EvaluationValidationError(
            f"Invalid evaluation for {candidate_stem}: at least one criterion "
            "records missing evidence, so the missing_information list must say "
            "what is missing."
        )

    sentence_count = count_sentences(payload.recommendation_rationale)
    if sentence_count < 2 or sentence_count > 3:
        raise EvaluationValidationError(
            f"Invalid evaluation for {candidate_stem}: the recommendation rationale "
            "must be two or three sentences."
        )

    return Evaluation(
        candidate_stem=candidate_stem,
        source_pdf_filename=source_pdf_filename,
        source_pdf_path=source_pdf_path,
        full_name=payload.full_name,
        headline=payload.headline,
        criteria=ordered,
        strengths=tuple(payload.strengths),
        concerns=tuple(payload.concerns),
        missing_information=tuple(payload.missing_information),
        recommendation=payload.recommendation,
        recommendation_rationale=payload.recommendation_rationale,
        tie_break=payload.tie_break,
        weighted_score=weighted_score(ordered, rubric),
    )


def validate_interview_questions(raw: dict, candidate_stem: str) -> InterviewQuestionSet:
    try:
        result = InterviewQuestionSet.model_validate(raw)
    except ValidationError as exc:
        raise EvaluationValidationError(
            f"Invalid interview questions for {candidate_stem}: "
            f"{_safe_validation_details(exc)}"
        ) from exc
    if not result.questions:
        raise EvaluationValidationError(
            f"Invalid interview questions for {candidate_stem}: no questions were returned."
        )
    return result
