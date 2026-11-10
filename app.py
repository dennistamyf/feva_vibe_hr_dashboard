"""Local Streamlit entry point for the HR screening workflow."""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit executes this file directly; make the project package importable
# regardless of the shell's current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from hr_screening.config import OUTPUT_ROOT, provider_status
from hr_screening.errors import HRScreeningError, InputValidationError
from hr_screening.inputs import (
    discover_batch,
    list_batch_keys,
    list_listing_keys,
    validate_selection,
)
from hr_screening.workflow import RunResult, run_screening

st.set_page_config(
    page_title="Local HR Screening",
    page_icon="📄",
    layout="wide",
)


def _default_index(options: list[str], preferred: str) -> int:
    return options.index(preferred) if preferred in options else 0


def _render_result(result: RunResult) -> None:
    st.success(f"Completed bundle: {result.output_dir}")
    st.code(str(result.output_dir), language=None)

    columns = st.columns(4)
    columns[0].metric("CVs discovered", result.discovered_count)
    columns[1].metric("Candidates evaluated", result.evaluated_count)
    columns[2].metric("Candidates selected", len(result.selected))
    columns[3].metric("Top N requested", result.top_n)

    st.markdown("### Created artifacts")
    for name in result.artifacts:
        st.markdown(f"- `{name}`")

    scoring_path = result.output_dir / "scoring_sheet.md"
    if scoring_path.is_file():
        st.download_button(
            "Download scoring_sheet.md",
            data=scoring_path.read_bytes(),
            file_name="scoring_sheet.md",
            mime="text/markdown",
            key=f"download_scoring_{result.timestamp}",
        )

    st.markdown("### Selected candidates")
    for evaluation in result.selected:
        question_path = (
            result.output_dir
            / "interview_questions"
            / f"{evaluation.candidate_stem}.md"
        )
        pdf_path = (
            result.output_dir
            / "selected_candidates"
            / evaluation.source_pdf_filename
        )
        with st.expander(
            f"{evaluation.full_name} — {evaluation.weighted_score:.1f} / 100 "
            f"— {evaluation.recommendation}"
        ):
            st.text(
                f"Source CV: {evaluation.source_pdf_filename}\n"
                f"CV headline: {evaluation.headline}\n"
                f"Recommendation: {evaluation.recommendation}"
            )
            if pdf_path.is_file():
                st.download_button(
                    f"Download {evaluation.source_pdf_filename}",
                    data=pdf_path.read_bytes(),
                    file_name=evaluation.source_pdf_filename,
                    mime="application/pdf",
                    key=f"download_pdf_{result.timestamp}_{evaluation.candidate_stem}",
                )
            if question_path.is_file():
                st.download_button(
                    f"Download interview questions — {evaluation.full_name}",
                    data=question_path.read_bytes(),
                    file_name=question_path.name,
                    mime="text/markdown",
                    key=f"download_questions_{result.timestamp}_{evaluation.candidate_stem}",
                )

    if result.tie_break_notes:
        st.info("Tie-break used: " + " ".join(result.tie_break_notes))

    if scoring_path.is_file():
        with st.expander("Preview scoring sheet", expanded=False):
            st.markdown(scoring_path.read_text(encoding="utf-8"))


def _render_output_viewer() -> None:
    """A panel to browse and view any previously completed output bundle."""
    output_dirs: list[Path] = []
    if OUTPUT_ROOT.is_dir():
        for entry in sorted(OUTPUT_ROOT.iterdir(), reverse=True):
            if entry.is_dir() and entry.name != ".staging":
                score = entry / "scoring_sheet.md"
                if score.is_file():
                    output_dirs.append(entry)

    if not output_dirs:
        return

    st.divider()
    st.markdown("## 📂 Browse previous outputs")

    labels = [d.name for d in output_dirs]
    selected_name = st.selectbox(
        "Select a completed screening bundle",
        options=labels,
        index=0,
        key="output_viewer_select",
    )
    selected = OUTPUT_ROOT / selected_name

    with st.container(border=True):
        st.markdown(f"**Bundle:** `{selected_name}`")

        # Read the run header from the scoring sheet
        score_path = selected / "scoring_sheet.md"
        if score_path.is_file():
            raw = score_path.read_text(encoding="utf-8")
            header_lines = []
            for line in raw.splitlines():
                if line.startswith("## "):
                    break
                header_lines.append(line)
            st.markdown("\n".join(header_lines))

        col1, col2, col3 = st.columns([1, 1, 2])

        if score_path.is_file():
            col1.download_button(
                "📄 Download scoring sheet",
                data=score_path.read_bytes(),
                file_name="scoring_sheet.md",
                mime="text/markdown",
                key="output_viewer_dl_score",
            )

        interviews_dir = selected / "interview_questions"
        if interviews_dir.is_dir():
            qfiles = sorted(interviews_dir.iterdir())
            if col2.button(f"📝 Download all questions ({len(qfiles)})", key="output_viewer_dl_all_q"):
                combined = ""
                for qf in qfiles:
                    combined += qf.read_text(encoding="utf-8") + "\n---\n"
                combined_bytes = combined.encode("utf-8")
                col2.download_button(
                    "Save all questions",
                    data=combined_bytes,
                    file_name="all_interview_questions.md",
                    mime="text/markdown",
                    key="output_viewer_dl_combined",
                )

        selected_dir = selected / "selected_candidates"
        pdf_count = 0
        if selected_dir.is_dir():
            pdf_count = len(list(selected_dir.glob("*.pdf")))
        col3.markdown(f"Candidates selected: **{pdf_count}**")

    # Preview the scoring sheet rendered
    if score_path.is_file():
        raw = score_path.read_text(encoding="utf-8")
        with st.expander("Preview scoring sheet", expanded=True):
            st.markdown(raw)

    # Interview questions per selected candidate
    if interviews_dir.is_dir():
        qfiles = sorted(interviews_dir.iterdir())
        if qfiles:
            st.markdown("### Interview questions")
            for qf in qfiles:
                stem = qf.stem
                with st.expander(f"💬 {stem}", expanded=False):
                    st.markdown(qf.read_text(encoding="utf-8"))
                    st.download_button(
                        f"Download {qf.name}",
                        data=qf.read_bytes(),
                        file_name=qf.name,
                        mime="text/markdown",
                        key=f"output_viewer_q_{stem}",
                    )

    # Selected candidate CVs
    if selected_dir.is_dir():
        pdfs = sorted(selected_dir.glob("*.pdf"))
        if pdfs:
            st.markdown("### Selected candidate CVs")
            for pdf_path in pdfs:
                with st.expander(f"📄 {pdf_path.name}", expanded=False):
                    st.download_button(
                        f"Download {pdf_path.name}",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        key=f"output_viewer_pdf_{pdf_path.stem}",
                    )


def _render_error(message: str) -> None:
    st.error(message)
    st.caption(
        "The run is not successful. No completed screening bundle is presented "
        "for this failed attempt."
    )


st.title("Local HR Screening")
st.caption(
    "Decision support for one local HR reviewer. Every candidate is evaluated "
    "before any ranking or selection. This app does not make a hiring decision."
)

with st.expander("Scope and guardrails", expanded=False):
    st.markdown(
        "- Fictional classroom CVs only; no real personal data.\n"
        "- Local, single-user, file-based storage. No login, database, or public "
        "deployment.\n"
        "- CV and listing text are treated as untrusted data, not instructions.\n"
        "- Missing evidence is recorded as missing; it is never filled in.\n"
        "- Location, nationality, and work-authorization signals are not scoring "
        "factors.\n"
        "- The provider key is never displayed, logged, sent in a prompt, or written "
        "to output."
    )

status = provider_status()
if status.configured:
    st.success(
        f"Provider configured. Model handle: `{status.model_handle}`. "
        "The provider key is never displayed."
    )
else:
    st.warning(status.safe_message)

listing_keys = list_listing_keys()
batch_keys = list_batch_keys()

if not listing_keys:
    st.error(
        "No listing folders were found under HR_dummy_data/listing. "
        "The run cannot start."
    )
    st.stop()
if not batch_keys:
    st.error(
        "No candidate batch folders were found under HR_dummy_data/candidates. "
        "The run cannot start."
    )
    st.stop()

select_columns = st.columns(3)
with select_columns[0]:
    listing_key = st.selectbox(
        "Job listing and scoring template",
        options=listing_keys,
        index=_default_index(listing_keys, "listing_01"),
        key="listing_key",
    )
with select_columns[1]:
    batch_key = st.selectbox(
        "Candidate batch",
        options=batch_keys,
        index=_default_index(batch_keys, "batch_01"),
        key="batch_key",
    )

batch = None
batch_error: str | None = None
try:
    batch = discover_batch(batch_key)
except InputValidationError as exc:
    batch_error = str(exc)

count = batch.count if batch is not None else 0
with select_columns[2]:
    if count:
        if "top_n" not in st.session_state:
            st.session_state.top_n = min(3, count)
        st.session_state.top_n = max(1, min(int(st.session_state.top_n), count))
        top_n = st.number_input(
            "Shortlist size (top N)",
            min_value=1,
            max_value=count,
            step=1,
            key="top_n",
            help="Must be a whole number from 1 to the number of discovered CVs.",
        )
    else:
        top_n = 0
        st.number_input(
            "Shortlist size (top N)",
            min_value=1,
            max_value=1,
            value=1,
            step=1,
            key="top_n_disabled",
            disabled=True,
        )

validation_error: str | None = None
selection = None
if batch_error:
    validation_error = batch_error
elif count:
    try:
        selection = validate_selection(listing_key, batch_key, top_n)
    except InputValidationError as exc:
        validation_error = str(exc)

if count:
    st.info(
        f"Discovered **{count}** CV PDF(s) in `{batch_key}`. "
        f"The default shortlist is **{min(3, count)}**; you may choose 1 to {count}."
    )
    if batch is not None:
        with st.expander(f"Discovered CV files ({count})", expanded=False):
            for pdf_path in batch.pdf_paths:
                st.markdown(f"- `{pdf_path.name}`")
if validation_error and validation_error != batch_error:
    st.error(validation_error)

can_run = bool(status.configured and selection is not None and count > 0)
run_clicked = st.button(
    "Start screening",
    type="primary",
    disabled=not can_run,
    help=(
        "Configure the provider privately before starting."
        if not status.configured
        else "Screen every candidate, then rank and select the top N."
    ),
)

st.caption(
    "Screening runs one candidate at a time. Ranking and selection happen only "
    "after every candidate has been evaluated and validated."
)

if run_clicked and can_run:
    st.session_state.pop("last_result", None)
    st.session_state.pop("last_error", None)

    status_box = st.status("Starting screening run...", expanded=True)
    progress_bar = st.progress(0.0, text="Validating inputs and provider...")
    note = st.empty()
    note.caption(
        "All candidates must finish before ranking. The app does not cancel a run."
    )

    def on_progress(stage: str, current: int, total: int, label: str) -> None:
        if stage == "validating":
            progress_bar.progress(0.0, text="Validating inputs and provider...")
        elif stage == "extracting":
            progress_bar.progress(
                0.05,
                text=f"Extracting CV text {current} of {total}: {label}",
            )
        elif stage == "screening":
            fraction = 0.10 + 0.80 * (current / max(total, 1))
            progress_bar.progress(
                min(fraction, 0.90),
                text=f"Screening {current} of {total}: {label}",
            )
        elif stage == "ranking":
            progress_bar.progress(
                0.92,
                text="All candidates evaluated. Ranking and selecting...",
            )
        elif stage == "questions":
            fraction = 0.94 + 0.04 * (current / max(total, 1))
            progress_bar.progress(
                min(fraction, 0.98),
                text=f"Generating interview questions {current} of {total}: {label}",
            )
        elif stage == "writing":
            progress_bar.progress(0.99, text="Writing the timestamped bundle...")

    try:
        result = run_screening(
            listing_key=listing_key,
            batch_key=batch_key,
            top_n=top_n,
            progress=on_progress,
        )
    except HRScreeningError as exc:
        st.session_state["last_error"] = str(exc)
        status_box.update(label="Screening failed", state="error", expanded=True)
        progress_bar.empty()
        _render_error(str(exc))
    except Exception as exc:  # keep unexpected details out of the UI
        message = (
            f"Unexpected error ({type(exc).__name__}). The run was stopped; "
            "no completed bundle is presented."
        )
        st.session_state["last_error"] = message
        status_box.update(label="Screening failed", state="error", expanded=True)
        progress_bar.empty()
        _render_error(message)
    else:
        st.session_state["last_result"] = result
        status_box.update(label="Screening complete", state="complete", expanded=False)
        progress_bar.progress(1.0, text="Screening complete")
        _render_result(result)

# Output viewer panel — browse any previously completed bundle
_render_output_viewer()

if "last_error" in st.session_state and not run_clicked:
    st.markdown("## Last failed run")
    _render_error(st.session_state["last_error"])
if "last_result" in st.session_state and not run_clicked:
    st.markdown("## Last completed run")
    _render_result(st.session_state["last_result"])
