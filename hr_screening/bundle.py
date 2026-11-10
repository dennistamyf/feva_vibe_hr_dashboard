"""Timestamped bundle writer with staging and no-overwrite behavior."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .config import PROJECT_ROOT
from .errors import OutputWriteError
from .inputs import Selection
from .models import Evaluation, InterviewQuestionSet
from .ranking import RankingResult
from .rubric import Rubric

_STAGING_PREFIX = ".staging_"


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except (ValueError, OSError):
        return str(path)


def _escape(value: object) -> str:
    text = str(value).replace("|", r"\|").replace("\r", " ").replace("\n", "<br>")
    return text.strip()


def _bullets(items: tuple[str, ...] | list[str], empty: str = "None documented.") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item.strip()}" for item in items if item.strip()) or f"- {empty}"


def _contribution(score: int, weight: float) -> str:
    value = Decimal(score) / Decimal("5") * Decimal(str(weight))
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def unique_timestamp(output_root: Path) -> str:
    """Return a new YYYYMMDD_HHMMSS name, moving forward if needed."""

    output_root = Path(output_root)
    now = datetime.now().replace(microsecond=0)
    for offset in range(0, 3600):
        stamp = (now + timedelta(seconds=offset)).strftime("%Y%m%d_%H%M%S")
        if not (output_root / stamp).exists():
            return stamp
    raise OutputWriteError(
        "Could not create a new timestamped output folder. No bundle was written."
    )


def create_staging(output_root: Path) -> Path:
    output_root = Path(output_root)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        stage = output_root / f"{_STAGING_PREFIX}{uuid.uuid4().hex}"
        stage.mkdir()
    except OSError as exc:
        raise OutputWriteError(
            f"Could not create the temporary output folder under {output_root}."
        ) from exc
    return stage


def cleanup_staging(stage: Path) -> None:
    shutil.rmtree(stage, ignore_errors=True)


def commit_staging(stage: Path, output_root: Path, timestamp: str) -> Path:
    final = Path(output_root) / timestamp
    if final.exists():
        raise OutputWriteError(
            f"Output folder already exists and was not overwritten: {final}"
        )
    try:
        os.replace(stage, final)
    except OSError as exc:
        raise OutputWriteError(
            f"Could not move the completed bundle into {final}. "
            "The staged folder was removed and no partial bundle was left."
        ) from exc
    return final


def _listing_title(listing_text: str) -> str:
    first = listing_text.splitlines()[0].strip() if listing_text.splitlines() else ""
    if first.lower().startswith("job listing:"):
        return first.split(":", 1)[1].strip()
    return first or "Selected role"


def _render_scoring_sheet(
    selection: Selection,
    rubric: Rubric,
    model_handle: str,
    timestamp: str,
    ranking: RankingResult,
    evaluated_count: int,
) -> str:
    listing = selection.listing
    batch = selection.batch
    selected_stems = {item.evaluation.candidate_stem for item in ranking.selected}

    lines: list[str] = [
        "# HR Screening Scoring Sheet",
        "",
        "## Run header",
        "",
        f"- **Listing:** {listing.key} — {_listing_title(listing.listing_text)}",
        f"- **Listing file:** {_relative(listing.listing_text_path)}",
        f"- **Scoring template:** {_relative(listing.scoring_template_path)}",
        f"- **Candidate batch:** {batch.key}",
        f"- **Model handle:** {model_handle}",
        f"- **Timestamp:** {timestamp}",
        f"- **Top N:** {selection.top_n}",
        f"- **CVs discovered:** {batch.count}",
        f"- **Candidates evaluated:** {evaluated_count}",
        f"- **Candidates selected:** {len(ranking.selected)}",
        "- **Run status:** complete",
        "",
        "## Ranking",
        "",
        f"Tie-break rule: prefer more direct evidence of {rubric.tie_break_primary}, "
        "then more recent relevant experience.",
        "",
        "| Rank | Candidate | Weighted score | Recommendation | Selected |",
        "|---:|---|---:|---|---|",
    ]

    for item in ranking.ranked:
        evaluation = item.evaluation
        lines.append(
            f"| {item.rank} | {_escape(evaluation.full_name)} | "
            f"{evaluation.weighted_score:.1f} / 100 | "
            f"{_escape(evaluation.recommendation)} | "
            f"{'Yes' if evaluation.candidate_stem in selected_stems else 'No'} |"
        )

    lines.extend(["", "## Tie-break record", ""])
    if ranking.tie_break_notes:
        lines.extend(f"- {note}" for note in ranking.tie_break_notes)
    else:
        lines.append("- No equal weighted scores occurred; the tie-break was not used.")

    lines.extend(["", "## Candidate evaluations", ""])
    for item in ranking.ranked:
        evaluation = item.evaluation
        selected = evaluation.candidate_stem in selected_stems
        lines.extend(
            [
                f"### Rank {item.rank}: {evaluation.full_name} — "
                f"{evaluation.weighted_score:.1f} / 100",
                "",
                f"- **Source PDF:** `{evaluation.source_pdf_filename}`",
                f"- **CV headline:** {evaluation.headline}",
                f"- **Recommendation:** {evaluation.recommendation}",
                f"- **Selected for shortlist:** {'Yes' if selected else 'No'}",
                "",
                f"**Recommendation rationale:** {evaluation.recommendation_rationale}",
                "",
                "**Strengths:**",
                "",
                _bullets(evaluation.strengths),
                "",
                "**Concerns:**",
                "",
                _bullets(evaluation.concerns),
                "",
                "**Missing information:**",
                "",
                _bullets(evaluation.missing_information),
                "",
                f"**Tie-break evidence (level "
                f"{evaluation.tie_break.primary_evidence_level}):** "
                f"{evaluation.tie_break.primary_evidence}",
                "",
                f"**Most recent relevant experience:** "
                f"{evaluation.tie_break.most_recent_relevant_role} at "
                f"{evaluation.tie_break.most_recent_relevant_employer} "
                f"({_recency_text(evaluation)})",
                "",
                "#### Criterion scores",
                "",
                "| Criterion | Weight | Score (0–5) | Contribution | Evidence | Source |",
                "|---|---:|---:|---:|---|---|",
            ]
        )
        for criterion, assessment in zip(rubric.criteria, evaluation.criteria):
            evidence = _escape(assessment.evidence)
            if assessment.evidence_missing:
                evidence += " _(missing evidence)_"
            lines.append(
                f"| {_escape(criterion.name)} | {criterion.weight:g}% | "
                f"{assessment.score} | {_contribution(assessment.score, criterion.weight)} | "
                f"{evidence} | {_escape(assessment.source)} |"
            )
        lines.extend(
            [
                "",
                f"**Weighted overall score:** {evaluation.weighted_score:.1f} / 100",
                "",
                "Contributions are rounded to one decimal for display; the weighted "
                "overall score is calculated from the unrounded criterion values.",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            "This scoring sheet is decision support only. It records model-assisted "
            "evidence against the approved rubric; it is not an automatic hiring "
            "decision or a prediction of job performance. A human reviewer must verify "
            "the cited CV evidence and decide whether to act. Location, nationality, "
            "and work-authorization signals were not used as scoring factors. If such "
            "information matters to the role, the reviewer should inspect the source CV "
            "directly.",
            "",
        ]
    )
    return "\n".join(lines)


def _recency_text(evaluation: Evaluation) -> str:
    tie = evaluation.tie_break
    if tie.most_recent_relevant_is_current:
        return "current"
    if tie.most_recent_relevant_end_year is not None:
        return f"ended {tie.most_recent_relevant_end_year}"
    return "no documented year"


def _render_question_file(
    selection: Selection,
    evaluation: Evaluation,
    questions: InterviewQuestionSet,
) -> str:
    lines = [
        f"# Interview Questions — {evaluation.full_name}",
        "",
        f"- **Listing:** {selection.listing.key} — "
        f"{_listing_title(selection.listing.listing_text)}",
        f"- **Source CV:** `{evaluation.source_pdf_filename}`",
        f"- **CV headline:** {evaluation.headline}",
        f"- **Recommendation:** {evaluation.recommendation}",
        f"- **Weighted score:** {evaluation.weighted_score:.1f} / 100",
        "",
        "## Questions",
        "",
    ]
    for index, item in enumerate(questions.questions, start=1):
        lines.append(f"{index}. **{item.question.strip()}**")
        lines.append(f"   - Based on: {item.based_on.strip()}")
        lines.append("")
    lines.extend(
        [
            "---",
            "",
            "These questions are preparation aids based on the validated evaluation "
            "and CV evidence. They are not a hiring decision or a substitute for human "
            "judgement.",
            "",
        ]
    )
    return "\n".join(lines)


def write_bundle(
    stage: Path,
    timestamp: str,
    selection: Selection,
    rubric: Rubric,
    model_handle: str,
    evaluations: list[Evaluation],
    ranking: RankingResult,
    questions_by_stem: dict[str, InterviewQuestionSet],
) -> None:
    """Write exactly the three approved artifact groups into the staging folder."""

    selected_dir = stage / "selected_candidates"
    questions_dir = stage / "interview_questions"
    try:
        selected_dir.mkdir()
        questions_dir.mkdir()
    except OSError as exc:
        raise OutputWriteError("Could not create the bundle folders.") from exc

    for item in ranking.selected:
        evaluation = item.evaluation
        destination = selected_dir / evaluation.source_pdf_filename
        try:
            if destination.exists():
                raise OutputWriteError(
                    f"Duplicate selected PDF filename would overwrite an earlier copy: "
                    f"{evaluation.source_pdf_filename}"
                )
            shutil.copy2(evaluation.source_pdf_path, destination)
        except OutputWriteError:
            raise
        except OSError as exc:
            raise OutputWriteError(
                f"Could not copy selected CV: {evaluation.source_pdf_filename}"
            ) from exc

    scoring_sheet = _render_scoring_sheet(
        selection=selection,
        rubric=rubric,
        model_handle=model_handle,
        timestamp=timestamp,
        ranking=ranking,
        evaluated_count=len(evaluations),
    )
    try:
        (stage / "scoring_sheet.md").write_text(scoring_sheet, encoding="utf-8")
    except OSError as exc:
        raise OutputWriteError("Could not write scoring_sheet.md.") from exc

    for item in ranking.selected:
        evaluation = item.evaluation
        questions = questions_by_stem.get(evaluation.candidate_stem)
        if questions is None:
            raise OutputWriteError(
                f"Interview questions are missing for selected candidate "
                f"{evaluation.candidate_stem}."
            )
        path = questions_dir / f"{evaluation.candidate_stem}.md"
        try:
            path.write_text(
                _render_question_file(selection, evaluation, questions),
                encoding="utf-8",
            )
        except OSError as exc:
            raise OutputWriteError(
                f"Could not write interview questions for "
                f"{evaluation.candidate_stem}."
            ) from exc


def artifact_names(final_dir: Path) -> list[str]:
    """Return relative artifact paths for the success view."""

    names: list[str] = []
    for path in sorted(final_dir.rglob("*")):
        if path.is_file():
            names.append(str(path.relative_to(final_dir)))
    return names
