"""End-to-end screening orchestration.

Order is deliberate: validate inputs and provider, extract every CV locally,
evaluate every candidate, validate every response, then rank, select, generate
questions, and only then stage and commit the bundle.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .bundle import (
    artifact_names,
    cleanup_staging,
    commit_staging,
    create_staging,
    unique_timestamp,
    write_bundle,
)
from .config import DATA_ROOT, Settings, load_settings
from .errors import (
    DuplicateIdentityError,
    HRScreeningError,
    InputValidationError,
    PdfExtractionError,
    RunInProgressError,
)
from .inputs import Selection, validate_selection
from .models import (
    Evaluation,
    InterviewQuestionSet,
    validate_evaluation_payload,
    validate_interview_questions,
)
from .pdf_extract import extract_pdf_text
from .prompts import (
    build_evaluation_prompt,
    build_interview_questions_prompt,
)
from .provider import OpenRouterProvider
from .ranking import RankedCandidate, RankingResult, rank_and_select
from .rubric import Rubric, parse_rubric

ProgressCallback = Callable[[str, int, int, str], None]

_RUN_LOCK = threading.Lock()


class ProviderProtocol(Protocol):
    def complete_json(
        self, system_prompt: str, user_prompt: str, candidate_label: str
    ) -> dict: ...


@dataclass(frozen=True)
class RunResult:
    output_dir: Path
    timestamp: str
    listing_key: str
    batch_key: str
    model_handle: str
    top_n: int
    discovered_count: int
    evaluated_count: int
    selected: tuple[Evaluation, ...]
    ranked: tuple[RankedCandidate, ...]
    tie_break_notes: tuple[str, ...]
    artifacts: tuple[str, ...]


def _emit(
    callback: ProgressCallback | None,
    stage: str,
    current: int,
    total: int,
    label: str,
) -> None:
    if callback is not None:
        callback(stage, current, total, label)


def _identity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _check_identity_collisions(
    evaluations: list[Evaluation],
    batch_pdf_names: list[str],
) -> None:
    by_name: dict[str, Evaluation] = {}
    for evaluation in evaluations:
        key = _identity_key(evaluation.full_name)
        previous = by_name.get(key)
        if previous is not None:
            raise DuplicateIdentityError(
                f"Candidate identity collision: '{evaluation.full_name}' appears in "
                f"both {previous.source_pdf_filename} and "
                f"{evaluation.source_pdf_filename}. No ranking or bundle was "
                "produced; rename or separate the files for reviewer disambiguation."
            )
        by_name[key] = evaluation

    stem_to_file = {
        _identity_key(Path(name).stem): name for name in batch_pdf_names
    }
    for evaluation in evaluations:
        other = stem_to_file.get(_identity_key(evaluation.full_name))
        if other and other != evaluation.source_pdf_filename:
            raise DuplicateIdentityError(
                f"Filename/name collision: candidate '{evaluation.full_name}' in "
                f"{evaluation.source_pdf_filename} has the same normalized name as "
                f"source file {other}. No ranking or bundle was produced; rename or "
                "separate the files for reviewer disambiguation."
            )


def _extract_all(
    selection: Selection,
    extractor: Callable[[Path], str],
    progress: ProgressCallback | None,
) -> dict[str, str]:
    texts: dict[str, str] = {}
    total = selection.batch.count
    for index, pdf_path in enumerate(selection.batch.pdf_paths, start=1):
        _emit(progress, "extracting", index, total, pdf_path.stem)
        try:
            text = extractor(pdf_path)
        except PdfExtractionError:
            raise
        except Exception as exc:
            raise PdfExtractionError(
                f"CV PDF could not be read: {pdf_path.name} "
                f"({type(exc).__name__})."
            ) from exc
        if not isinstance(text, str) or not text.strip():
            raise PdfExtractionError(
                f"CV PDF contains no extractable text: {pdf_path.name}. "
                "The run was stopped before evaluating this candidate."
            )
        texts[pdf_path.name] = text
    return texts


def _run_screening_locked(
    listing_key: str,
    batch_key: str,
    top_n: int,
    *,
    settings: Settings | None,
    provider: ProviderProtocol | None,
    extractor: Callable[[Path], str],
    data_root: Path,
    output_root: Path,
    progress: ProgressCallback | None,
    env: Mapping[str, str] | None,
    env_file: Path | None,
) -> RunResult:
    _emit(progress, "validating", 0, 1, "inputs")

    selection = validate_selection(
        listing_key, batch_key, top_n, data_root=Path(data_root)
    )
    rubric: Rubric = parse_rubric(
        selection.listing.scoring_template,
        source_name=str(selection.listing.scoring_template_path),
    )

    if settings is None:
        settings = load_settings(env=env, env_file=env_file)
    if provider is None:
        provider = OpenRouterProvider(settings)

    cv_texts = _extract_all(selection, extractor, progress)

    evaluations: list[Evaluation] = []
    total = selection.batch.count
    for index, pdf_path in enumerate(selection.batch.pdf_paths, start=1):
        _emit(progress, "screening", index, total, pdf_path.stem)
        system_prompt, user_prompt = build_evaluation_prompt(
            listing_text=selection.listing.listing_text,
            rubric=rubric,
            candidate_cv_text=cv_texts[pdf_path.name],
        )
        raw = provider.complete_json(
            system_prompt, user_prompt, candidate_label=pdf_path.stem
        )
        evaluation = validate_evaluation_payload(
            raw,
            rubric=rubric,
            candidate_stem=pdf_path.stem,
            source_pdf_filename=pdf_path.name,
            source_pdf_path=pdf_path,
        )
        evaluations.append(evaluation)

    if len(evaluations) != selection.batch.count:
        raise InputValidationError(
            "The screening set is incomplete. Ranking was not started and no "
            "bundle was written."
        )
    _check_identity_collisions(
        evaluations, [p.name for p in selection.batch.pdf_paths]
    )

    _emit(progress, "ranking", total, total, "all candidates")
    ranking: RankingResult = rank_and_select(
        evaluations, rubric=rubric, top_n=selection.top_n
    )
    if len(ranking.selected) != selection.top_n:
        raise InputValidationError(
            "Selection did not produce the requested number of candidates. "
            "No bundle was written."
        )

    questions_by_stem: dict[str, InterviewQuestionSet] = {}
    for index, item in enumerate(ranking.selected, start=1):
        evaluation = item.evaluation
        _emit(progress, "questions", index, len(ranking.selected), evaluation.candidate_stem)
        system_prompt, user_prompt = build_interview_questions_prompt(
            listing_text=selection.listing.listing_text,
            rubric=rubric,
            candidate_cv_text=cv_texts[evaluation.source_pdf_filename],
            evaluation=evaluation,
        )
        raw = provider.complete_json(
            system_prompt, user_prompt, candidate_label=evaluation.candidate_stem
        )
        questions_by_stem[evaluation.candidate_stem] = validate_interview_questions(
            raw, evaluation.candidate_stem
        )

    _emit(progress, "writing", 0, 1, "bundle")
    stage = create_staging(Path(output_root))
    try:
        timestamp = unique_timestamp(Path(output_root))
        write_bundle(
            stage=stage,
            timestamp=timestamp,
            selection=selection,
            rubric=rubric,
            model_handle=settings.model,
            evaluations=evaluations,
            ranking=ranking,
            questions_by_stem=questions_by_stem,
        )
        final_dir = commit_staging(stage, Path(output_root), timestamp)
    except Exception:
        cleanup_staging(stage)
        raise

    _emit(progress, "writing", 1, 1, "complete")
    return RunResult(
        output_dir=final_dir,
        timestamp=timestamp,
        listing_key=listing_key,
        batch_key=batch_key,
        model_handle=settings.model,
        top_n=selection.top_n,
        discovered_count=selection.batch.count,
        evaluated_count=len(evaluations),
        selected=tuple(item.evaluation for item in ranking.selected),
        ranked=ranking.ranked,
        tie_break_notes=ranking.tie_break_notes,
        artifacts=tuple(artifact_names(final_dir)),
    )


def run_screening(
    listing_key: str,
    batch_key: str,
    top_n: int,
    *,
    settings: Settings | None = None,
    provider: ProviderProtocol | None = None,
    extractor: Callable[[Path], str] = extract_pdf_text,
    data_root: Path = DATA_ROOT,
    output_root: Path | None = None,
    progress: ProgressCallback | None = None,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> RunResult:
    """Run one complete screening attempt.

    The function is synchronous and one-at-a-time. It never ranks before all
    candidates are evaluated and never commits a partial bundle.
    """

    if not _RUN_LOCK.acquire(blocking=False):
        raise RunInProgressError(
            "A screening run is already in progress. Wait for it to finish."
        )
    try:
        root = Path(data_root)
        final_output_root = Path(output_root) if output_root is not None else root / "output"
        return _run_screening_locked(
            listing_key,
            batch_key,
            top_n,
            settings=settings,
            provider=provider,
            extractor=extractor,
            data_root=root,
            output_root=final_output_root,
            progress=progress,
            env=env,
            env_file=env_file,
        )
    except HRScreeningError:
        raise
    finally:
        _RUN_LOCK.release()
