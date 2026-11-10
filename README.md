# Local HR Screening App

A local, single-user Streamlit app for screening one fictional candidate batch
against one job listing and its matching scoring template. It is decision
support for a human reviewer; it does not make a hiring decision.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Configure the provider privately by copying `.env.example` to `.env` and
filling in the two settings:

```text
OPENROUTER_API_KEY=<configured privately>
OPENROUTER_MODEL=<approved non-secret model handle>
```

Never commit `.env`, paste the key into chat, or write it into output data.
Without the key and model handle, the app shows a safe missing-provider message
and makes no request.

## Start

```bash
.venv/bin/streamlit run app.py
```

The app defaults to `listing_01`, `batch_01`, and top N = 3. All paths are
resolved from this project folder, not from the shell's working directory.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests use temporary fixtures and a fake provider. They do not call
OpenRouter, read a real key, modify the supplied CVs, or write into the real
`HR_dummy_data/output/` folder.

## Successful output

A successful run writes a new folder such as
`HR_dummy_data/output/20261110_034736/` containing exactly:

```text
selected_candidates/
  <selected PDFs with original filenames>
scoring_sheet.md
interview_questions/
  <candidate_file_stem>.md
```

The scoring sheet covers every screened candidate, not only the selected ones.
Every evaluation records criterion-level evidence or explicit missing
information, strengths, concerns, the application-calculated weighted score, a
recommendation, and any tie-break used.
