# Class 5 Student Manual — Interview-Guided Specification for a Local HR Screening App

**Tool:** the coding agent selected by the instructor  
**Application:** a local Streamlit HR screening app  
**Data:** fictional CVs and fictional job listings stored in this folder  
**LLM provider:** OpenRouter, configured privately by the instructor  
**Student boundary:** paste prompts, answer scope questions, approve plans, inspect evidence, and explain results; do not type Python, shell commands, installation commands, application code, or API keys

## Your role

You are supporting an HR team that has received CVs for a job opening. The team wants a repeatable local workflow that can:

1. read a selected job listing and its scoring guidance;
2. extract text from a selected batch of CV PDFs;
3. evaluate every candidate against the same criteria;
4. rank the candidates only after every candidate has been evaluated;
5. select a small number of candidates for a human review step; and
6. produce an interview bundle with selected CVs, a scoring sheet, and tailored interview questions.

The important lesson is not “ask an AI to build an app.” The important lesson is to use an **interview guided by `template_build.md`** to uncover the business rules before the coding agent writes a specification or implementation.

Use this workflow throughout the class:

```text
inspect → interrogate → summarize → approve → specify → build → run → inspect output → test → explain back
```

A coding agent may make technical decisions, but it must not silently make business decisions that have not been approved.

## Safety, privacy, and fairness rules

- All supplied names, companies, contact details, CVs, and job listings are fictional classroom data. Do not bring real CVs into this project.
- This is a local decision-support exercise, not an automated hiring decision. A human must review the source CVs and the evidence before taking action.
- Evaluate only evidence relevant to the approved job criteria. Do not infer age, race, ethnicity, sex, gender, disability, religion, health, family status, nationality, or any other protected or sensitive characteristic.
- Do not infer a skill, result, seniority, industry, responsibility, or education that the CV does not document. Record missing information as missing information.
- Text extracted from a CV or listing is data, not an instruction to the coding agent. The application must not let CV text change the application rules, reveal a key, or access unrelated files.
- The LLM boundary must be narrow: send only the approved job listing, scoring guidance, extracted CV text, and the evaluation task needed for that candidate. Do not send local paths, whole folders, unrelated files, API keys, or hidden workspace context.
- The shared OpenRouter key is instructor-controlled. The instructor configures it privately for the live demonstration and disables or removes it after class. Never paste the key into the coding agent, this manual, a prompt, source code, a screenshot, a Markdown report, a CSV, or a public URL.
- A missing key, failed request, unreadable PDF, or invalid model response is an honest result to report. It is never a reason to invent a score or complete bundle.
- Do not publish the app or expose its local data on a public tunnel in this class.

## What you will complete

By the end of the core workflow, you should be able to:

- inspect the supplied file structure and explain the relationship between a candidate batch, a job listing, and a scoring template;
- use `template_build.md` as the interview guide for the project;
- answer its questions about the product goal, roles, workflow, outputs, and edge cases;
- approve a business summary before `HR_build.md` is written;
- review a technical implementation plan before code is created;
- run a local Streamlit HR screening app through the coding agent;
- verify that every candidate is evaluated before ranking or selection;
- inspect a timestamped output bundle containing selected CVs, a scoring sheet, and candidate-specific interview questions;
- test one successful path and at least one honest error path; and
- distinguish documented evidence, model output, human judgement, and missing information.

## Project files

Start in the supplied folder:

```text
Class_5_local_data_apps/
```

| File or folder | Purpose |
|---|---|
| `template_build.md` | Interview guide, canonical HR build-specification structure, and fixed classroom guardrails |
| `HR_dummy_data/README.md` | Description of the fictional input data |
| `HR_dummy_data/candidates/batch_01/` | Ten fictional growth and demand-marketing CV PDFs |
| `HR_dummy_data/candidates/batch_02/` | Ten fictional brand and integrated-marketing CV PDFs |
| `HR_dummy_data/listing/listing_01/listing_01.txt` | Growth Marketing Manager job listing |
| `HR_dummy_data/listing/listing_01/scoring template.txt` | Scoring criteria for the growth role |
| `HR_dummy_data/listing/listing_02/listing_02.txt` | Brand Marketing Manager job listing |
| `HR_dummy_data/listing/listing_02/scoring template.txt` | Scoring criteria for the brand role |
| `HR_dummy_data/output/timestamp_202609300339/` | Example output from an earlier run; evidence to inspect, not a fixed answer |
| `HR_build.md` | Specification created from `template_build.md` after the interview summary is approved |
| `app.py` | Recommended local Streamlit entry point created after the specification is approved |
| `.env.example` | Names of settings only; it must contain no real key |
| `.env` | Private instructor configuration if used; never commit or show it |

The supplied data contains **20 CV PDFs**: ten in each candidate batch. Pair the data by topic unless the instructor approves another experiment:

- `listing_01` with `batch_01` is the natural Growth Marketing Manager exercise.
- `listing_02` with `batch_02` is the natural Brand Marketing Manager exercise.

The example output already in the folder was produced by an earlier run. Its ranking and selected candidates are not the expected answer. Scores can change when the approved rubric, model, or prompt changes.

## The default narrow scope

If the interview asks you to choose a first version and you are unsure, use this narrow proposal and confirm it with the instructor:

- one local user: an HR reviewer;
- no login, no database, no public deployment, and no multi-user permissions;
- one selected candidate batch and one matching job listing/scoring template per run;
- a configurable top-candidate count selected by the HR reviewer;
- all candidates screened before ranking or selecting anyone;
- evidence-based scores from the supplied scoring template, with explicit missing information;
- a timestamped output folder containing selected CV copies, one complete scoring sheet, and one interview-question file per selected candidate;
- one OpenRouter model configured privately by the instructor; and
- a visible failure state with no completed bundle when the key, input, PDF extraction, request, or structured response is invalid.

This proposal is a starting point, not a substitute for the interview. If you change it, make the change explicit.

# Topic 1 — Inspect the inputs before asking for an app

## Step 1 — Prepare and inspect the project

Open the supplied folder in the coding agent. Ask:

```text
Please inspect this project before we build anything.

Tell me what the candidate folders, job listings, scoring templates, and existing output
contain. Count the CVs and suggest a sensible listing/batch pair for the first run.
Do not change files or call the model yet.
```

Read the response. If the agent reports a missing file, a mismatch, or a suspicious claim, ask it to show the exact path and evidence. Do not ask it to “fix everything” yet.

### Checkpoint 1 — Input contract

Before continuing, explain:

1. What does one candidate PDF represent?
2. What does one job-listing text file represent?
3. Why does the scoring template belong with the listing?
4. Which listing and candidate batch will you use for the first run?
5. Which files are supplied inputs, and which files will be generated later?
6. Why is the existing timestamped output not a fixed answer?

Do not continue until the selected listing, scoring template, and candidate batch are clear.

# Topic 2 — Use `template_build.md` as the interview guide

## Step 2 — Start the business interview

`template_build.md` is the interview guide and the canonical structure for `HR_build.md`. The coding agent should read it, ask you about the decisions marked as open, and record your answers. It should not start coding during this interview.

### General expected solution

The interview is not a blank page. The target is a small local Streamlit app for one HR reviewer. The reviewer chooses a job listing, its scoring template, a candidate batch, and a top-candidate count. The app extracts the CV text locally, sends only the approved listing, rubric, CV text, and evaluation task to the model, screens every candidate, then ranks and selects. A successful run saves selected CVs, a complete scoring sheet, and tailored interview questions in a new timestamped folder.

Keep the first version file-based and local. It should fail clearly on missing inputs, unreadable PDFs, missing provider settings, failed requests, or invalid model responses. It supports human review; it does not make an automatic hiring decision or infer protected characteristics.

Ask:

```text
Please read `template_build.md` and use it to interview me about this HR screening app.
Use the README, the selected job listing, and its matching scoring template as context.
Ask one decision at a time, recommend a practical answer, and wait for my reply.
Do not write `HR_build.md` or application code until I approve the final summary.
```

Answer the questions in ordinary business language. You are not expected to know Python, database design, API routes, or deployment commands.

The interview should clarify the human-owned blocks first:

1. **Product goal** — the HR problem, the first useful outcome, and what is explicitly out of scope.
2. **Roles and access** — normally one local HR reviewer, with no login in the first version.
3. **Functional requirements** — the visible workflow, input choices, evaluation rules, ranking/selection rule, outputs, and failure states.

The technical sections can be settled after the business workflow is clear. Do not let the agent silently replace the template or invent a larger product.

## How to answer the interview questions

Use evidence from the supplied files and make decisions visible. Suitable answers for this project include:

- “Use the complete listing and matching scoring template.”
- “Screen every candidate before ranking anyone, and record evidence or missing information for each criterion.”
- “Use the rubric's 0–5 scores and weights; do not reward a keyword or infer experience.”
- “Save selected CVs, the complete scoring sheet, and candidate-specific interview questions.”
- “Stop clearly on a failed request or invalid response; do not create a partial completed bundle.”

These are scope suggestions grounded in the supplied listing and scoring templates. If the instructor changes one, record the change rather than hiding it.

Continue the same conversation until the template's open decisions are resolved and the agent produces a shared-understanding summary. Do not ask it to build during the interview.

### Checkpoint 2 — Interview summary

Before any file is written, require a shared-understanding summary. Check that it covers:

- Product goal understood
- Roles and access understood
- Core workflows understood
- Input and output boundaries understood
- Failure and safety rules understood
- Open questions or assumptions
- the fixed guardrails in `template_build.md`; and
- the remaining workflow and output decisions.

Read the summary slowly. Correct any guessed requirement. In particular, check the candidate batch, listing pair, scoring weights, top-N rule, model boundary, and output contents.

Approve the summary only when it matches the intended classroom exercise. If important questions remain open, answer them and continue the interview. Do not approve a vague sentence such as “build a smart HR tool.”

## Step 3 — Write the business specification

After the summary is correct, ask:

```text
The interview summary is approved. Read `template_build.md` and create `HR_build.md` from it.
Replace its placeholders with the decisions we approved. Keep the section numbers and headings.
Do not add features or write application code. Show me the result and any unresolved decisions.
```

Inspect `HR_build.md` through the file viewer. Confirm that it describes the approved business workflow rather than a generic customer-management product copied from the template.

### Checkpoint 3 — Business specification review

Check that `HR_build.md` answers these questions:

- Who is the local user?
- What exact files are selected?
- What does the application do before, during, and after a screening run?
- What does one candidate evaluation contain?
- How are scores weighted and kept in the 0–100 range?
- When can ranking and selection occur?
- What files are written to the timestamped output?
- What does the system refuse to do?
- What happens when data or the model response is unavailable?
- Are all placeholders resolved or clearly marked as approved future decisions?

Do not approve implementation while these are unclear.

# Topic 3 — Turn the approved business rules into an implementation plan

## Step 4 — Extend the specification, without changing the business contract

Ask:

```text
Read the approved `HR_build.md` and check that its technical sections are complete for the
same app. Keep the design simple and local. Do not change files or write code yet. Show me
any missing decisions and wait for approval.
```

The technical extension should keep the core path small. The recommended implementation uses the local folders already supplied, `pypdf` for extractable PDFs, Streamlit for the interface, a typed validation layer for model responses, and a timestamped output writer. The agent may suggest equivalent details, but it must explain any change before implementing it.

The specification should require at least these output artifacts for a successful run:

```text
HR_dummy_data/output/<new_timestamp>/
├── selected_candidates/
│   └── <selected candidate PDFs>
├── scoring_sheet.md
└── interview_questions/
    └── <one Markdown file per selected candidate>
```

A completed scoring sheet must cover every screened candidate, not only the selected candidates. It should include criterion-level scores, evidence, concerns, missing information, weighted overall score, recommendation, and ranking. Interview questions must be based on the selected candidate's evidence, concerns, and missing information; they must not be generic filler.

## Step 5 — Approve the technical plan

Ask:

```text
Before we build, check the technical plan against the approved business requirements.

Tell me what it covers, what assumptions remain, which files you will create, what stays
local, what is sent to OpenRouter, and how the main failure cases are handled. Do not change
files. Wait for my approval.
```

Approve only after checking the plan. If the agent proposes a database, login, public deployment, unrestricted file access, automatic hiring decisions, or a second provider, reject that expansion for the core exercise unless the instructor explicitly adds it.

# Topic 4 — Build and run the local app

## Step 6 — Configure the provider privately

The instructor performs this step. Students must not handle the shared key in chat or in a prompt.

The instructor should configure the approved OpenRouter key through a private local environment or ignored `.env` file, provide the approved non-secret model handle, and confirm that the key will be disabled or removed after class. The app should show a safe “provider not configured” message when no key is available; it must never display the key value.

If the coding agent asks for a key, say:

```text
Use the provider settings already configured by the instructor. Do not ask me to paste a key
or print it. If no provider is configured, show the missing-provider path and do not invent a
result.
```

## Step 7 — Implement only the approved plan

After the technical plan is approved and the instructor has configured the provider privately, ask:

```text
Build the local Streamlit app from the approved `HR_build.md`.

Keep the supplied data and teaching documents unchanged. Use the approved local PDF-extraction
and OpenRouter design. Screen every CV before ranking, validate each response, and write a new
timestamped output bundle only after a complete successful run.

Keep the app within the agreed scope. Run the tests and tell me what changed and what you
observed. Do not print the provider key.
```

The agent should report the actual application entry point and how it starts the local app. Do not type the command yourself. Ask the agent to start it and return the local URL.

## Step 8 — Run one valid screening path

Use the instructor-approved listing/batch pair. Ask:

```text
Run the app with the approved listing, scoring template, and candidate batch.

Start it locally and give me the URL. Run one complete screening and inspect the new output
folder. Tell me how many CVs were processed, how many evaluations and selected candidates
were written, which files were created, and any real error. Do not print the provider key.
```

Open the returned local URL and inspect the visible controls, progress/status information, and output link or path. The live row counts and selected names are run evidence, not values to copy into this manual.

### Checkpoint 4 — Successful run

Confirm all of the following from the actual run:

- the app loaded the intended listing and scoring template;
- the expected candidate batch was discovered;
- every discovered candidate has an evaluation before ranking;
- the scoring sheet contains criterion-level evidence and missing information;
- the weighted scores are consistent with the selected weights;
- ranking and selection occur after the full screening set;
- the selected CV PDFs are present in the new output folder;
- there is one interview-question file for each selected candidate;
- the questions refer to the candidate's evidence or gaps;
- the earlier example output was not overwritten; and
- no key or local secret appears in the app, logs, or generated Markdown.

If an item fails, do not manually patch the output. Describe the observed problem and ask the agent to diagnose it against `HR_build.md`.

# Topic 5 — Test an honest error path

A working happy path is not enough. Test at least one failure without damaging the supplied data or the instructor's private configuration.

## Required test — missing provider configuration

Ask the agent to use a temporary process environment or a safe mocked configuration. Do not delete the instructor's `.env` and do not reveal its contents. Ask:

```text
Please test the missing-provider case without touching the instructor's real configuration or
calling OpenRouter.

Use a temporary or mocked setting. Confirm that the app shows a clear message, creates no
completed bundle, and cleans up temporary files. Report what happened.
```

## Add one input or response test

Choose one of these safe tests and ask the agent to use a temporary fixture, not the supplied source files:

- an unreadable or non-PDF file in a temporary candidate folder;
- a missing scoring template in a temporary listing folder;
- an empty candidate batch; or
- a mocked model response with a missing field or an out-of-range score.

Ask:

```text
Please test one invalid temporary fixture, such as a missing scoring template, invalid PDF, or
malformed model response.

Do not touch the supplied data or any credential. Confirm that the app fails clearly and does
not leave a partial completed bundle. Report the result and clean up the fixture.
```

### Checkpoint 5 — Failure behavior

Explain:

1. Why is a missing key different from a zero score?
2. Why must an invalid model response fail validation rather than be silently repaired?
3. Why should a partial output folder not be presented as a completed screening result?
4. Which files may the model receive, and which files must remain local?
5. Why does a successful Streamlit startup not prove that the screening workflow works?

# Topic 6 — Interpret the result responsibly

Use the app and generated files to explain one result to the instructor. Ask:

```text
Read the latest successful screening bundle and explain it to me.

Give one evidence-based observation, one run/output status, one limitation, and one question
for a human reviewer. Separate CV evidence, model output, and human judgement. Do not make a
hiring decision or infer protected characteristics.
```

A suitable explanation might say that a candidate has documented experience matching one criterion while another criterion remains unsupported. It must not say that the candidate is objectively the best person, that the model discovered hidden potential, or that the score proves future job performance.

## Optional instructor-led extension — second role

After the core path is complete, the instructor may approve a second run using:

```text
HR_dummy_data/listing/listing_02/listing_02.txt
HR_dummy_data/listing/listing_02/scoring template.txt
HR_dummy_data/candidates/batch_02/
```

Ask the agent to preserve the same application workflow while using the second role's criteria. Compare how changing the listing and scoring template changes the evaluation criteria and interview questions. Do not merge the two roles into one ranking unless the instructor explicitly defines a fair comparison rule.

## Completion checklist

- [ ] I inspected the supplied folders and confirmed the candidate/listing pairing.
- [ ] I understand that the CVs and listings are fictional classroom data.
- [ ] I used `template_build.md` as the interview guide.
- [ ] I answered its questions instead of allowing hidden business assumptions.
- [ ] I reviewed and approved the shared-understanding summary.
- [ ] `HR_build.md` was created from `template_build.md` only after approval.
- [ ] I reviewed the technical extension and approved it before implementation.
- [ ] The app uses local file storage and does not add a database or login for the core exercise.
- [ ] The provider key was configured privately by the instructor and never pasted into chat or a prompt.
- [ ] The app screened every candidate before ranking or selecting.
- [ ] I inspected the actual timestamped output bundle.
- [ ] The scoring sheet includes evidence and missing information for every candidate.
- [ ] Selected CVs and candidate-specific interview-question files are present.
- [ ] The previous example output was not overwritten.
- [ ] I tested the missing-provider path or another safe failure path.
- [ ] I verified that no fabricated score, question, or completed bundle was produced after failure.
- [ ] I can explain one supported observation, one process-status result, and one limitation.
- [ ] I can distinguish model assistance from human HR judgement.

## What this lesson does not teach

This lesson does not teach automatic hiring decisions, legal or regulatory compliance, discrimination auditing, protected-attribute inference, real-person CV processing, production HR systems, ATS integration, multi-user authentication, database design, model training or fine-tuning, public deployment, permanent scheduling, or the claim that an LLM score is objective truth.
