"""Safe tests using temporary fixtures and a fake provider.

No test calls OpenRouter, reads a real key, modifies the supplied CVs, or writes
into the real HR_dummy_data/output folder.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter

from hr_screening.config import Settings, load_settings, provider_status
from hr_screening.errors import (
    DuplicateIdentityError,
    EvaluationValidationError,
    InputValidationError,
    MissingProviderConfig,
    OutputWriteError,
    PdfExtractionError,
    ProviderRequestError,
    ResponseParseError,
)
from hr_screening.inputs import discover_batch, validate_selection
from hr_screening.models import validate_evaluation_payload
from hr_screening.pdf_extract import extract_pdf_text
from hr_screening.provider import OpenRouterProvider, parse_json_object
from hr_screening.ranking import rank_and_select
from hr_screening.rubric import parse_rubric
from hr_screening.workflow import run_screening

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CRITERIA = [
    ("Revenue and funnel ownership", 25, "Look for qualified pipeline, conversion, activation, CAC, or revenue outcomes."),
    ("Channel depth and experimentation", 20, "Look for hands-on channel ownership and disciplined testing."),
    ("Lifecycle, CRM, and automation", 15, "Look for segmentation, nurture, onboarding, retention, or automation."),
    ("Analytics and attribution", 15, "Look for dashboards, measurement design, attribution, or analytics fluency."),
    ("B2B SaaS and sales partnership", 15, "Look for business buyers, sales-assisted journeys, or close Sales work."),
    ("Communication and operating leadership", 10, "Look for clear briefs, stakeholder management, and ownership."),
]

RUBRIC_TEMPLATE = "\n".join(
    [
        "Evaluate each candidate using the complete job listing as context.",
        "",
        "Score each criterion from 0 to 5 and explain the score with evidence from the CV.",
        "",
        *[f"- {name}: {weight}%. {guidance}" for name, weight, guidance in CRITERIA],
        "",
        "For every criterion, quote concrete CV evidence and identify the role or project.",
        "",
        "Rank all candidates from highest to lowest overall score. Resolve equal scores by "
        "preferring the candidate with more direct evidence of qualified-pipeline ownership, "
        "then the candidate with more recent relevant experience. State when this tie-break "
        "is used.",
    ]
)

LISTING_TEXT = """\
Job Listing: Growth Marketing Manager
Company: Test Co
Location: Remote within the United States

The role owns growth experiments, paid channels, lifecycle programs, analytics, and
sales partnership for a B2B SaaS product.
"""


def make_payload(
    name: str,
    scores: list[int],
    *,
    level: int = 2,
    end_year: int | None = 2024,
    current: bool = False,
    recommendation: str = "Yes",
    missing_indices: set[int] | None = None,
    rationale: str = (
        "The CV documents relevant work against the rubric. "
        "A human reviewer should verify the depth of ownership."
    ),
) -> dict:
    missing_indices = missing_indices or set()
    criteria = []
    missing_information: list[str] = []
    for index, ((criterion, _weight, _guidance), score) in enumerate(zip(CRITERIA, scores)):
        if index in missing_indices:
            criteria.append(
                {
                    "criterion": criterion,
                    "score": 0,
                    "evidence": "No CV evidence found.",
                    "source": "Not stated in CV",
                    "evidence_missing": True,
                }
            )
            missing_information.append(f"No evidence was documented for {criterion}.")
        else:
            criteria.append(
                {
                    "criterion": criterion,
                    "score": score,
                    "evidence": f"The CV documents concrete evidence for {criterion}.",
                    "source": "Growth Marketing Manager at Example Co",
                    "evidence_missing": False,
                }
            )
    return {
        "full_name": name,
        "headline": "Growth Marketing Manager",
        "criteria": criteria,
        "strengths": ["Documented relevant experience."],
        "concerns": ["Some ownership limits remain."],
        "missing_information": missing_information,
        "recommendation": recommendation,
        "recommendation_rationale": rationale,
        "tie_break": {
            "primary_evidence_level": level,
            "primary_evidence": "The CV documents direct ownership in a named role.",
            "most_recent_relevant_role": "Growth Marketing Manager",
            "most_recent_relevant_employer": "Example Co",
            "most_recent_relevant_end_year": None if current else end_year,
            "most_recent_relevant_is_current": current,
        },
    }


class FakeProvider:
    def __init__(
        self,
        payloads: dict[str, dict],
        questions: dict[str, dict] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.payloads = payloads
        self.questions = questions or {}
        self.fail_on = fail_on
        self.calls: list[dict] = []

    def complete_json(
        self, system_prompt: str, user_prompt: str, candidate_label: str
    ) -> dict:
        is_question = "<validated_evaluation>" in user_prompt
        self.calls.append(
            {
                "label": candidate_label,
                "is_question": is_question,
                "system": system_prompt,
                "user": user_prompt,
            }
        )
        if self.fail_on == candidate_label:
            raise ProviderRequestError(
                f"Provider request failed for {candidate_label} in the test fixture."
            )
        if is_question:
            return self.questions.get(
                candidate_label,
                {
                    "questions": [
                        {
                            "question": (
                                f"What evidence supports your work on "
                                f"{candidate_label}?"
                            ),
                            "based_on": "Validated criterion evidence",
                        }
                    ]
                },
            )
        return self.payloads[candidate_label]


class FakeHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "fixture error") -> None:
        super().__init__(message)
        self.status_code = status_code


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            content = item
        else:
            content = json.dumps(item)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def make_project(tmp: Path, n: int = 3):
    data = tmp / "HR_dummy_data"
    listing_dir = data / "listing" / "listing_01"
    listing_dir.mkdir(parents=True)
    (listing_dir / "listing_01.txt").write_text(LISTING_TEXT, encoding="utf-8")
    (listing_dir / "scoring template.txt").write_text(
        RUBRIC_TEMPLATE, encoding="utf-8"
    )
    batch_dir = data / "candidates" / "batch_01"
    batch_dir.mkdir(parents=True)
    for index in range(n):
        (batch_dir / f"cand_{index}.pdf").write_bytes(b"%PDF-1.4 fake fixture")
    return data, listing_dir, batch_dir


def fake_extractor(path: Path) -> str:
    return (
        f"CV text for {path.stem}\n"
        "EXPERIENCE\nGrowth Marketing Manager at Example Co\n"
        "- Owned paid channels, lifecycle programs, analytics, and Sales partnership."
    )


def evaluation_for(name: str, scores: list[int], *, level: int = 2, end_year=2024, recommendation: str = "Yes"):
    rubric = parse_rubric(RUBRIC_TEMPLATE)
    payload = make_payload(
        name,
        scores,
        level=level,
        end_year=end_year,
        current=False,
        recommendation=recommendation,
    )
    stem = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    return validate_evaluation_payload(
        payload,
        rubric=rubric,
        candidate_stem=stem,
        source_pdf_filename=f"{stem}.pdf",
        source_pdf_path=Path(f"/tmp/{stem}.pdf"),
    )


class TestInputsAndConfig(unittest.TestCase):
    def test_supplied_batches_have_ten_pdfs(self):
        self.assertEqual(discover_batch("batch_01").count, 10)
        self.assertEqual(discover_batch("batch_02").count, 10)

    def test_second_role_pair_is_discoverable(self):
        selection = validate_selection("listing_02", "batch_02", 3)
        self.assertEqual(selection.listing.key, "listing_02")
        self.assertEqual(selection.batch.key, "batch_02")
        self.assertEqual(selection.batch.count, 10)

    def test_missing_scoring_template_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, listing_dir, _ = make_project(Path(tmp))
            (listing_dir / "scoring template.txt").unlink()
            with self.assertRaises(InputValidationError) as caught:
                validate_selection("listing_01", "batch_01", 3, data_root=data)
            self.assertIn("scoring template is missing", str(caught.exception))
            self.assertIn("scoring template.txt", str(caught.exception))

    def test_empty_batch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, _, _ = make_project(Path(tmp), n=0)
            with self.assertRaises(InputValidationError) as caught:
                validate_selection("listing_01", "batch_01", 1, data_root=data)
            self.assertIn("No PDF files were found", str(caught.exception))

    def test_non_pdf_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, _, batch_dir = make_project(Path(tmp), n=3)
            (batch_dir / ".DS_Store").write_bytes(b"junk")
            (batch_dir / "notes.txt").write_text("ignore me")
            self.assertEqual(discover_batch("batch_01", data_root=data).count, 3)

    def test_top_n_bounds_and_integer_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, _, _ = make_project(Path(tmp), n=3)
            self.assertEqual(
                validate_selection("listing_01", "batch_01", 1, data_root=data).top_n,
                1,
            )
            self.assertEqual(
                validate_selection("listing_01", "batch_01", 3, data_root=data).top_n,
                3,
            )
            for bad in (0, 4, 2.5, "3", True):
                with self.subTest(bad=bad):
                    with self.assertRaises(InputValidationError):
                        validate_selection(
                            "listing_01", "batch_01", bad, data_root=data
                        )

    def test_multiple_listing_text_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, listing_dir, _ = make_project(Path(tmp))
            (listing_dir / "extra.txt").write_text("another listing")
            with self.assertRaises(InputValidationError) as caught:
                validate_selection("listing_01", "batch_01", 1, data_root=data)
            self.assertIn("Multiple job-listing text files", str(caught.exception))

    def test_missing_provider_config_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MissingProviderConfig) as caught:
                load_settings(env={}, env_file=Path(tmp) / ".env")
            message = str(caught.exception)
            self.assertIn("OPENROUTER_API_KEY", message)
            self.assertIn("OPENROUTER_MODEL", message)
            self.assertIn("No model request was made", message)

    def test_settings_repr_hides_key(self):
        settings = Settings(api_key="unit-test-placeholder", model="test/model")
        self.assertNotIn("unit-test-placeholder", repr(settings))
        self.assertIn("test/model", repr(settings))

    def test_env_file_loading_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "OPENROUTER_API_KEY=from-file\nOPENROUTER_MODEL=file-model\n",
                encoding="utf-8",
            )
            settings = load_settings(env={}, env_file=env_path)
            self.assertEqual(settings.model, "file-model")
            self.assertEqual(settings.api_key, "from-file")
            settings = load_settings(
                env={"OPENROUTER_MODEL": "env-model"}, env_file=env_path
            )
            self.assertEqual(settings.model, "env-model")

    def test_provider_status_does_not_expose_key(self):
        status = provider_status(env={}, env_file=Path("/nonexistent/.env"))
        self.assertFalse(status.configured)
        self.assertIsNone(status.model_handle)
        self.assertNotIn("sk-", status.safe_message)


class TestRubric(unittest.TestCase):
    def test_listing_01_weights_and_tie_break(self):
        path = PROJECT_ROOT / "HR_dummy_data/listing/listing_01/scoring template.txt"
        rubric = parse_rubric(path.read_text(encoding="utf-8"))
        self.assertEqual(
            [c.name for c in rubric.criteria],
            [name for name, _weight, _guidance in CRITERIA],
        )
        self.assertEqual([c.weight for c in rubric.criteria], [25, 20, 15, 15, 15, 10])
        self.assertEqual(rubric.weight_total, 100)
        self.assertIn("qualified-pipeline ownership", rubric.tie_break_primary)

    def test_listing_02_weights_and_tie_break(self):
        path = PROJECT_ROOT / "HR_dummy_data/listing/listing_02/scoring template.txt"
        rubric = parse_rubric(path.read_text(encoding="utf-8"))
        self.assertEqual(
            [c.name for c in rubric.criteria],
            [
                "Brand strategy and positioning",
                "Integrated campaign leadership",
                "Customer insight and market understanding",
                "Creative collaboration and storytelling",
                "Measurement and commercial judgment",
                "Cross-functional communication and delivery",
            ],
        )
        self.assertEqual(rubric.weight_total, 100)
        self.assertIn("positioning or campaign-platform ownership", rubric.tie_break_primary)

    def test_invalid_weight_total_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_rubric("- A: 90%. Guidance\n- B: 5%. Guidance")
        self.assertIn("must total 100%", str(caught.exception))


class TestPdfExtraction(unittest.TestCase):
    def test_unreadable_pdf_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.pdf"
            path.write_bytes(b"not a pdf")
            with self.assertRaises(PdfExtractionError) as caught:
                extract_pdf_text(path)
            self.assertIn("bad.pdf", str(caught.exception))

    def test_empty_text_pdf_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with path.open("wb") as handle:
                writer.write(handle)
            with self.assertRaises(PdfExtractionError) as caught:
                extract_pdf_text(path)
            self.assertIn("no extractable text", str(caught.exception))

    def test_supplied_cv_extracts_text(self):
        text = extract_pdf_text(
            PROJECT_ROOT / "HR_dummy_data/candidates/batch_01/maya_chen.pdf"
        )
        self.assertIn("Maya Chen", text)
        self.assertIn("Growth Marketing Manager", text)


class TestEvaluationValidation(unittest.TestCase):
    def setUp(self):
        self.rubric = parse_rubric(RUBRIC_TEMPLATE)
        self.scores = [5, 4, 3, 2, 1, 0]

    def validate(self, payload):
        return validate_evaluation_payload(
            payload,
            rubric=self.rubric,
            candidate_stem="cand_0",
            source_pdf_filename="cand_0.pdf",
            source_pdf_path=Path("/tmp/cand_0.pdf"),
        )

    def test_weighted_score_is_app_calculated(self):
        evaluation = self.validate(make_payload("Candidate Zero", self.scores))
        self.assertEqual(evaluation.weighted_score, 59.0)
        payload = make_payload("Candidate Zero", self.scores)
        payload["weighted_score"] = 999
        payload["unknown_field"] = "ignored"
        evaluation = self.validate(payload)
        self.assertEqual(evaluation.weighted_score, 59.0)

    def test_all_fives_is_one_hundred(self):
        evaluation = self.validate(make_payload("Candidate Zero", [5, 5, 5, 5, 5, 5]))
        self.assertEqual(evaluation.weighted_score, 100.0)

    def test_missing_criterion_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"].pop()
        with self.assertRaises(EvaluationValidationError) as caught:
            self.validate(payload)
        self.assertIn("missing criterion", str(caught.exception))

    def test_duplicate_criterion_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"].append(dict(payload["criteria"][0]))
        with self.assertRaises(EvaluationValidationError) as caught:
            self.validate(payload)
        self.assertIn("appears more than once", str(caught.exception))

    def test_unknown_criterion_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"][0]["criterion"] = "Invented criterion"
        with self.assertRaises(EvaluationValidationError) as caught:
            self.validate(payload)
        self.assertIn("unknown criterion", str(caught.exception))

    def test_harmless_criterion_formatting_is_mapped(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"][0]["criterion"] = "Revenue & funnel ownership"
        evaluation = self.validate(payload)
        self.assertEqual(
            evaluation.criteria[0].criterion, "Revenue and funnel ownership"
        )

    def test_score_out_of_range_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"][0]["score"] = 6
        with self.assertRaises(EvaluationValidationError) as caught:
            self.validate(payload)
        self.assertIn("less than or equal to 5", str(caught.exception))

    def test_non_integer_score_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"][0]["score"] = 4.5
        with self.assertRaises(EvaluationValidationError):
            self.validate(payload)

    def test_unknown_recommendation_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["recommendation"] = "Definitely"
        with self.assertRaises(EvaluationValidationError):
            self.validate(payload)

    def test_blank_evidence_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"][0]["evidence"] = "   "
        with self.assertRaises(EvaluationValidationError):
            self.validate(payload)

    def test_positive_score_with_missing_evidence_is_rejected(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"][0].update(
            {
                "score": 4,
                "evidence": "No CV evidence found.",
                "source": "Not stated in CV",
                "evidence_missing": True,
            }
        )
        with self.assertRaises(EvaluationValidationError) as caught:
            self.validate(payload)
        self.assertIn("positive score", str(caught.exception))

    def test_missing_evidence_requires_missing_information(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["criteria"][5].update(
            {
                "score": 0,
                "evidence": "No CV evidence found.",
                "source": "Not stated in CV",
                "evidence_missing": True,
            }
        )
        payload["missing_information"] = []
        with self.assertRaises(EvaluationValidationError) as caught:
            self.validate(payload)
        self.assertIn("missing_information", str(caught.exception))

    def test_rationale_must_be_two_or_three_sentences(self):
        payload = make_payload("Candidate Zero", self.scores)
        payload["recommendation_rationale"] = "One sentence only."
        with self.assertRaises(EvaluationValidationError):
            self.validate(payload)
        payload["recommendation_rationale"] = "One. Two. Three. Four."
        with self.assertRaises(EvaluationValidationError):
            self.validate(payload)


class TestRanking(unittest.TestCase):
    def test_tie_break_uses_primary_evidence_then_recency(self):
        rubric = parse_rubric(RUBRIC_TEMPLATE)
        low = evaluation_for("Low Evidence", [4, 4, 4, 4, 4, 4], level=0, end_year=2026)
        high_old = evaluation_for(
            "High Old", [4, 4, 4, 4, 4, 4], level=2, end_year=2022
        )
        high_new = evaluation_for(
            "High New", [4, 4, 4, 4, 4, 4], level=2, end_year=2025
        )
        result = rank_and_select([low, high_old, high_new], rubric, top_n=2)
        self.assertEqual(
            [item.evaluation.full_name for item in result.ranked],
            ["High New", "High Old", "Low Evidence"],
        )
        self.assertTrue(result.tie_break_notes)
        self.assertIn("Tie at 80.0", result.tie_break_notes[0])
        self.assertIn("qualified-pipeline ownership", result.tie_break_notes[0])

    def test_no_recommendation_gate(self):
        rubric = parse_rubric(RUBRIC_TEMPLATE)
        no_candidate = evaluation_for(
            "No Candidate", [5, 5, 5, 5, 5, 5], level=2, end_year=2026,
            recommendation="No",
        )
        yes_candidate = evaluation_for(
            "Yes Candidate", [4, 4, 4, 4, 4, 4], level=2, end_year=2026
        )
        result = rank_and_select([yes_candidate, no_candidate], rubric, top_n=1)
        self.assertEqual(result.selected[0].evaluation.full_name, "No Candidate")
        self.assertEqual(result.selected[0].evaluation.recommendation, "No")


class TestProvider(unittest.TestCase):
    def settings(self):
        return Settings(api_key="unit-test-placeholder", model="test/model")

    def test_rate_limit_retries_once(self):
        client = FakeClient([FakeHTTPError(429), {"ok": True}])
        sleeps: list[float] = []
        provider = OpenRouterProvider(
            self.settings(), client=client, sleep=sleeps.append
        )
        result = provider.complete_json("system", "user", "cand_0")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(client.chat.completions.calls, 2)
        self.assertEqual(sleeps, [2.0])

    def test_server_error_retries_once_then_reports(self):
        client = FakeClient([FakeHTTPError(500), FakeHTTPError(503)])
        provider = OpenRouterProvider(
            self.settings(), client=client, sleep=lambda _seconds: None
        )
        with self.assertRaises(ProviderRequestError) as caught:
            provider.complete_json("system", "user", "cand_0")
        self.assertEqual(client.chat.completions.calls, 2)
        self.assertIn("after one retry", str(caught.exception))
        self.assertNotIn("unit-test-placeholder", str(caught.exception))

    def test_non_retryable_error_does_not_retry(self):
        client = FakeClient([FakeHTTPError(400)])
        provider = OpenRouterProvider(
            self.settings(), client=client, sleep=lambda _seconds: None
        )
        with self.assertRaises(ProviderRequestError) as caught:
            provider.complete_json("system", "user", "cand_0")
        self.assertEqual(client.chat.completions.calls, 1)
        self.assertIn("HTTP 400", str(caught.exception))

    def test_json_fence_is_accepted(self):
        client = FakeClient(["```json\n{\"ok\": true}\n```"])
        provider = OpenRouterProvider(self.settings(), client=client)
        self.assertEqual(provider.complete_json("s", "u", "cand_0"), {"ok": True})

    def test_invalid_json_is_rejected(self):
        client = FakeClient(["this is not json"])
        provider = OpenRouterProvider(self.settings(), client=client)
        with self.assertRaises(ResponseParseError):
            provider.complete_json("s", "u", "cand_0")

    def test_parse_json_object_requires_an_object(self):
        with self.assertRaises(ResponseParseError):
            parse_json_object("[1, 2, 3]")


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data, self.listing_dir, self.batch_dir = make_project(self.root, n=3)
        self.output_root = self.data / "output"
        self.settings = Settings(api_key="unit-test-placeholder", model="test/model")
        self.payloads = {
            "cand_0": make_payload(
                "Candidate Zero",
                [5, 5, 5, 5, 5, 5],
                recommendation="Strong yes",
                current=True,
            ),
            "cand_1": make_payload(
                "Candidate One",
                [4, 4, 4, 4, 4, 4],
                recommendation="Yes",
                current=True,
            ),
            "cand_2": make_payload(
                "Candidate Two",
                [3, 3, 3, 3, 3, 3],
                recommendation="Maybe",
                missing_indices={5},
                current=True,
            ),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _run_workflow(self, provider=None, top_n=2, **kwargs):
        return run_screening(
            "listing_01",
            "batch_01",
            top_n,
            settings=kwargs.pop("settings", self.settings),
            provider=provider or FakeProvider(self.payloads),
            extractor=fake_extractor,
            data_root=self.data,
            output_root=self.output_root,
            env_file=self.root / "missing.env",
            **kwargs,
        )

    def test_successful_mock_run_writes_exact_bundle(self):
        provider = FakeProvider(self.payloads)
        result = self._run_workflow(provider=provider)
        self.assertTrue(result.output_dir.is_dir())
        self.assertRegex(result.output_dir.name, r"^\d{8}_\d{6}$")
        self.assertEqual(result.discovered_count, 3)
        self.assertEqual(result.evaluated_count, 3)
        self.assertEqual(len(result.selected), 2)

        expected = {
            "scoring_sheet.md",
            "selected_candidates/cand_0.pdf",
            "selected_candidates/cand_1.pdf",
            "interview_questions/cand_0.md",
            "interview_questions/cand_1.md",
        }
        self.assertEqual(set(result.artifacts), expected)

        scoring = (result.output_dir / "scoring_sheet.md").read_text(encoding="utf-8")
        for name in ("Candidate Zero", "Candidate One", "Candidate Two"):
            self.assertIn(name, scoring)
        self.assertIn("**Candidates evaluated:** 3", scoring)
        self.assertIn("**Candidates selected:** 2", scoring)
        self.assertIn("100.0 / 100", scoring)
        self.assertIn("80.0 / 100", scoring)
        self.assertIn("54.0 / 100", scoring)
        self.assertIn("No CV evidence found.", scoring)
        self.assertIn("No evidence was documented for", scoring)
        self.assertIn("Criterion scores", scoring)
        self.assertIn("Tie-break record", scoring)

        self.assertEqual(
            (result.output_dir / "selected_candidates/cand_0.pdf").read_bytes(),
            (self.batch_dir / "cand_0.pdf").read_bytes(),
        )
        questions = (result.output_dir / "interview_questions/cand_0.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Candidate Zero", questions)
        self.assertIn("Based on:", questions)

        # All three evaluations happen before any interview-question request.
        kinds = [call["is_question"] for call in provider.calls]
        self.assertEqual(kinds, [False, False, False, True, True])
        self.assertEqual(
            [call["label"] for call in provider.calls[:3]],
            ["cand_0", "cand_1", "cand_2"],
        )

        # The key and local fixture path never enter a prompt or output file.
        for call in provider.calls:
            self.assertNotIn("unit-test-placeholder", call["system"])
            self.assertNotIn("unit-test-placeholder", call["user"])
            self.assertNotIn(str(self.root), call["user"])
        for path in result.output_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"unit-test-placeholder", path.read_bytes())

    def test_second_run_creates_new_folder_and_preserves_first(self):
        first = self._run_workflow()
        first_scoring = (first.output_dir / "scoring_sheet.md").read_bytes()
        second = self._run_workflow()
        self.assertNotEqual(first.output_dir, second.output_dir)
        self.assertTrue(first.output_dir.is_dir())
        self.assertTrue(second.output_dir.is_dir())
        self.assertEqual(
            (first.output_dir / "scoring_sheet.md").read_bytes(), first_scoring
        )

    def test_provider_failure_stops_and_leaves_no_bundle(self):
        provider = FakeProvider(self.payloads, fail_on="cand_1")
        with self.assertRaises(ProviderRequestError) as caught:
            self._run_workflow(provider=provider)
        self.assertIn("cand_1", str(caught.exception))
        self.assertFalse(
            any(p.is_dir() for p in self.output_root.iterdir())
            if self.output_root.exists()
            else False
        )
        self.assertEqual(
            [call["label"] for call in provider.calls], ["cand_0", "cand_1"]
        )

    def test_malformed_response_leaves_no_bundle(self):
        provider = FakeProvider({"cand_0": {"full_name": "Only a name"}})
        with self.assertRaises(EvaluationValidationError):
            self._run_workflow(provider=provider)
        self.assertFalse(
            any(p.is_dir() for p in self.output_root.iterdir())
            if self.output_root.exists()
            else False
        )

    def test_out_of_range_score_leaves_no_bundle(self):
        payload = make_payload("Candidate Zero", [5, 5, 5, 5, 5, 5])
        payload["criteria"][0]["score"] = 6
        provider = FakeProvider({"cand_0": payload})
        with self.assertRaises(EvaluationValidationError):
            self._run_workflow(provider=provider)

    def test_duplicate_identity_leaves_no_bundle(self):
        payloads = dict(self.payloads)
        payloads["cand_1"] = make_payload(
            "Candidate Zero", [4, 4, 4, 4, 4, 4], current=True
        )
        provider = FakeProvider(payloads)
        with self.assertRaises(DuplicateIdentityError) as caught:
            self._run_workflow(provider=provider)
        message = str(caught.exception)
        self.assertIn("cand_0.pdf", message)
        self.assertIn("cand_1.pdf", message)

    def test_missing_provider_makes_no_request_and_writes_nothing(self):
        provider = FakeProvider(self.payloads)
        with self.assertRaises(MissingProviderConfig):
            run_screening(
                "listing_01",
                "batch_01",
                2,
                settings=None,
                provider=provider,
                extractor=fake_extractor,
                data_root=self.data,
                output_root=self.output_root,
                env={},
                env_file=self.root / "missing.env",
            )
        self.assertEqual(provider.calls, [])
        self.assertFalse(
            any(p.is_dir() for p in self.output_root.iterdir())
            if self.output_root.exists()
            else False
        )

    def test_unreadable_pdf_stops_before_any_provider_request(self):
        provider = FakeProvider(self.payloads)
        with self.assertRaises(PdfExtractionError) as caught:
            run_screening(
                "listing_01",
                "batch_01",
                2,
                settings=self.settings,
                provider=provider,
                extractor=extract_pdf_text,
                data_root=self.data,
                output_root=self.output_root,
            )
        self.assertIn("cand_0.pdf", str(caught.exception))
        self.assertEqual(provider.calls, [])

    def test_invalid_top_n_stops_before_any_provider_request(self):
        provider = FakeProvider(self.payloads)
        with self.assertRaises(InputValidationError):
            self._run_workflow(provider=provider, top_n=4)
        self.assertEqual(provider.calls, [])

    def test_invalid_interview_questions_leave_no_bundle(self):
        provider = FakeProvider(
            self.payloads, questions={"cand_0": {"questions": []}}
        )
        with self.assertRaises(EvaluationValidationError):
            self._run_workflow(provider=provider)
        self.assertFalse(
            any(p.is_dir() for p in self.output_root.iterdir())
            if self.output_root.exists()
            else False
        )

    def test_write_failure_cleans_staging(self):
        with patch(
            "hr_screening.workflow.write_bundle",
            side_effect=OutputWriteError("simulated write failure"),
        ):
            with self.assertRaises(OutputWriteError):
                self._run_workflow()
        if self.output_root.exists():
            self.assertFalse(
                any(p.is_dir() for p in self.output_root.iterdir()),
                "staging or timestamp folder remained after write failure",
            )


if __name__ == "__main__":
    unittest.main()
