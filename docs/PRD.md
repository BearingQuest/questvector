# QuestVector — Product Requirements Document

| Field | Value |
|---|---|
| Product | QuestVector: the Python desktop build (`qv` CLI and desktop app), and the planned browser app ([ADR-0016](decisions/0016-browser-app-static-pages.md)) |
| Owner | Dusten Harrison |
| Version | 0.2 — 28 Oct 2026 (adds the browser app); 0.1 — 15 Oct 2026 (first PRD, written after the 1.0.0 build) |
| Status | Draft for owner review |
| Build path | AI-directed. Requirements came from a Google Gemini brainstorming session; Claude built 1.0.0 from them. Changes go through a branch and pull request with CI checks; the owner approves every merge. |
| Cost constraint | $0 beyond the owner's Claude subscription: no paid APIs, no paid hosting (the browser app's static GitHub Pages site is free for a public repository) |
| Related documents | `docs/QuestVector_Spec.pdf` (how 1.0.0 works), `docs/decisions/` (why), `docs/BACKLOG.md` (planned work), `CHANGELOG.md` (what changed) |

This document states what QuestVector must do and why. The system spec
describes how the current build does it; where the two differ, this
document states the intent and the spec is updated to match. Every
requirement is marked **Built** (in 1.0.0 and covered by tests) or
**Planned** (with its backlog item). Anything not written here is out of
scope until the owner adds it.

---

## 1. Summary

QuestVector is a local-first career tool for experienced IT professionals.
The user keeps their career history as three Markdown files: capabilities,
chronology, and quantified impact. QuestVector scores that history against
a job description using a weighted, role-specific mission template; reports
the match score, gaps, and red flags; and compiles a tailored PDF or DOCX
resume bundle. Optionally, the user can ask an AI provider of their choice
to draft a resume summary, including a local model that never leaves the
machine.

It comes in two forms that share one Python core:

- **The desktop app and `qv` CLI** run from a local install (a release wheel
  or a clone). The dossier is plain Markdown in a local workspace folder.
- **The browser app** (planned,
  [ADR-0016](decisions/0016-browser-app-static-pages.md)) is for users who
  can't install software. It's a set of static files on this repository's
  GitHub Pages site, running the same core in Pyodide. The dossier stays in
  the browser, or in a folder the user picks on browsers that allow it.
  There is no backend, no account, and no data collection.

In both, nothing about the user's career data leaves their machine unless
they configure a remote AI provider and explicitly ask for a narrative. The
first browser version has no AI (R28).

## 2. Goals and non-goals

### Goals
- G1. Show the user, before they apply, how well their documented history
  covers a specific job description, and where the gaps and red flags are.
- G2. Keep career data private: stored locally, readable without
  QuestVector, and sent nowhere without an explicit user action.
- G3. Produce resume output an applicant tracking system (ATS) parses
  correctly and a recruiter can read.
- G4. Keep every generated claim traceable to the dossier: no invented
  titles, metrics, dates, or technology claims.
- G5. Work at $0: a local model must be a complete alternative to paid APIs.
  This applies to the desktop app; the browser app has no local model.
- G6. Be explainable: the user can see why a score is what it is.
- G7. Let others extend it: new mission templates and new AI providers
  without changes to core code.
- G8. Be usable by less-technical users with no install and no admin
  rights: the browser app works in current desktop Chrome, Safari and
  Firefox, and in Edge (expected but not yet tested) (§5.9). Mobile browsers aren't a goal until they've been tested.

### Non-goals
- Hosting, accounts, telemetry, or any public distribution channel other
  than release files on this repository's GitHub Releases and the browser
  app's static GitHub Pages site (ADR-0001, narrowed by ADR-0014 and
  ADR-0016). The Pages site serves static files only: no backend and no
  data collection.
- Applying to jobs, scraping job boards, or tracking applications.
- Semantic or embedding-based matching. Keyword matching is a deliberate
  choice for predictability (ADR-0006); revisit only through a new decision.
- Writing the whole resume with AI. AI drafts the summary only; experience
  content comes from the dossier.

## 3. Users and use cases

| User | Use case |
|---|---|
| Experienced IT professional (5–10+ years) | Scores a job description before applying, sees gaps, decides whether to apply |
| Job seeker tailoring an application | Exports a resume bundle matched to one posting, optionally with an AI-drafted summary |
| Privacy-conscious user | Runs everything with a local model; no data leaves the machine |
| Less-technical job seeker (no install or admin rights) | Opens the browser app in a desktop browser, keeps the dossier in the browser or a chosen folder, scores job descriptions and exports a resume bundle (G8) |
| Template contributor | Writes a mission template for their field, validates it locally, and submits a pull request |
| Owner as developer and learner | Extends the tool through AI-directed development and uses it to learn local LLMs, testing, and CI |

## 4. Core concepts

- **Dossier.** Three Markdown files in a workspace: `Capabilities.md`,
  `Chronology.md`, `Impact.md`. The user owns and edits them directly.
- **Workspace.** A local folder created by `qv launch`, holding the dossier,
  templates, exported bundles, and the vault.
- **Mission template.** A YAML file of weighted categories, each with
  keywords, describing what a role type values (ADR-0003). Weights sum to 1.00.
- **G-Force score.** The weighted coverage of the template categories the
  posting asks about, as a percentage (coverage), with relevance, gaps, weak
  categories, red flags, and an alert level (ADR-0006, ADR-0033).
- **Bundle.** A PDF or DOCX compiled from the dossier, optionally with a match
  summary and an AI-drafted narrative.
- **Vault.** An encrypted local file holding the AI provider choice and keys
  (ADR-0002).
- **Provider.** An AI service that drafts the narrative: Anthropic, OpenAI,
  Gemini (remote), or Ollama (local) (ADR-0004, ADR-0005).

## 5. Functional requirements

Acceptance criteria use EARS-style phrasing.

### 5.1 Workspace and dossier

**R1 — Workspace setup.** **Built.**
- WHEN the user runs `qv launch --dir <path>`, THEN the system SHALL create
  the dossier stub files, `templates/starter/` with the bundled starter
  templates, an empty `templates/community/`, and `bundles/`.
- The system SHALL NOT overwrite any existing file.
- The system SHALL take an advisory lock before writing to a workspace, so
  two processes can't write at once.

**R2 — Dossier parsing.** **Built.**
- The system SHALL parse the three dossier files into structured data and
  keyword sets, and SHALL report a parse error with the file name rather than
  failing silently.
- Keyword sets SHALL be normalized (ADR-0027), and a role title in a
  Chronology heading SHALL count as a keyword.

### 5.2 Matching

**R3 — Score a job description.** **Built.**
- WHEN the user runs `qv sync-ast --target <file> --template <id>`, or runs a
  match in the desktop app, THEN the system SHALL show the G-Force coverage
  (the score over the categories the posting asks about), the relevance
  (template keywords the posting asks about, out of all template keywords),
  per-category coverage, gaps, weak categories, red flags, and alert level
  (ADR-0033).
- WHERE the posting asks about too few template keywords or categories, the
  alert level SHALL be LOW_RELEVANCE (unless a red flag makes it CRITICAL) and
  the result SHALL say so in plain words and suggest another template, and
  SHALL NOT show a coverage percentage to the reader ("not scored"; the
  number stays in `--json`). WHERE
  it asks about none, the result SHALL say "no template keywords found" and
  SHALL NOT show 100% or any other coverage number (ADR-0033).
- WHERE `--json` is given, the output SHALL be machine-readable.
- The result SHALL show, next to the score, how many of the posting's template
  keywords the dossier has ("N of M"), and for each category "N of M asked" or
  "not asked". The counts are display only (ADR-0030).
- The result SHALL list dossier lines where a negation (no, not, never,
  without, none, "training only") sits next to a keyword that matched, naming
  the file, heading, line and keyword. Warnings don't change the score or alert
  level (ADR-0030).
- The desktop app SHALL show the same result as the CLI, including weak
  categories, and both SHALL build it from one serializer.

**R4 — Scoring rules.** **Built.**
- The score SHALL follow the rules in `questvector/core/matcher.py` and spec
  Section 5. The same inputs SHALL always produce the same score.
- Job-description text, dossier text and template keywords SHALL be normalized
  the same way before they are compared (ADR-0027).
- A category with nothing relevant in the job description SHALL be left out
  of the score and of its weight total, so it neither raises nor lowers it
  (ADR-0033, which replaces the earlier "counts as full coverage" rule).
- Relevance SHALL count each distinct template keyword once, even when
  several categories list it. The low-relevance minimums (5 keywords, 2
  categories) SHALL be capped by the template's own size.

**R5 — Explain the score.** **Planned** (backlog item 10).
- The documentation SHALL include a worked example showing how one job
  description and one dossier produce a given score, so a user can check it
  by hand.

### 5.3 Mission templates

**R6 — Validation.** **Built.**
- WHEN the user runs `qv template validate <path>`, THEN the system SHALL
  report YAML syntax errors, missing required fields, and weights that don't
  sum to 1.00 (±0.005), and SHALL exit non-zero if the template is invalid.
- WHERE `--fix` is given, the system SHALL rescale weights to 1.00 and save
  the file.
- A template keyword that matching ignores (a stopword or one letter) SHALL be
  refused, naming the template, category and keyword (ADR-0030).

**R7 — Contribution path.** **Built** (15 Oct 2026).
- The repository SHALL provide a valid boilerplate at
  `templates/boilerplate.qv-mission.yaml` and a `templates/community/` folder.
- WHEN a pull request or push to `main` touches a template, the validator,
  or the workflow, THEN CI SHALL validate every template under `templates/`
  and fail if any is invalid (ADR-0007, ADR-0008).

### 5.4 Export

**R8 — Bundle export.** **Built.**
- WHEN the user runs `qv export --bundle <name> --format pdf|docx`, THEN the
  system SHALL write the bundle to `bundles/`, including a match summary when
  `--target` and `--template` are given.
- The bundle name SHALL be 1-64 letters, digits, `.`, `-` or `_`, starting
  with a letter or digit, and the file SHALL be written inside `bundles/`,
  from both `qv export` and the desktop app; any other name SHALL be refused
  with a plain error before anything is written (ADR-0029).
- WHERE a match summary is included, the bundle SHALL show the asked-keyword
  counts beside each category and the overall count, the coverage and the
  relevance, and the low-relevance note when it applies. It SHALL NOT include
  negation warnings (ADR-0030).

**R9 — ATS-safe resume output.** **Built** (backlog item 5; ADR-0032).
- WHERE the user runs `qv export --style resume` (or picks the Resume style in
  the desktop window), THEN the system SHALL write a resume instead of the match
  report. The report remains the default style.
- Exported resumes SHALL use a single column, with no tables, text boxes,
  columns, tab stops, or content in page headers and footers.
- Each role SHALL have a title line and a "Company | Mon YYYY – Mon YYYY" line,
  with the employer repeated on every role. The resume style SHALL require every
  Chronology heading in the form `Title — Employer (Mon YYYY – Mon YYYY)` (or
  `Present`) and SHALL name each heading that doesn't fit.
- The resume SHALL show the contact block from an optional `Contact.md`
  (name and email required), which SHALL stay on the machine and SHALL NOT be
  sent to an AI provider. Email and profile URLs SHALL be real hyperlinks.
- The resume SHALL show the summary (when one was generated, CLI only for now),
  Capability domain names only, up to 6 bullets per role, and the first Impact
  bullet of up to 5 groups. It SHALL NOT show the match score, a table or gaps.
- WHERE the user passes `--cutoff-years [N]` (20 when no value is given; 1 to
  60), roles that ended more than N years before today, measured on the end
  month, SHALL move to one dateless "Earlier Career" line, and no year before the
  cutoff SHALL appear in the file: a role whose own heading would print one is
  refused by name, and other lines that mention one are left out and reported.
  The cutoff is off by default.
- The desktop resume export has no summary yet (backlog item 15).

**R10 — Automated output check.** **Built** (backlog item 5; ADR-0032).
- The system SHALL check an exported DOCX by extracting its text two
  independent ways (python-docx paragraphs and the raw `word/document.xml`),
  with no system tools and no new dependency.
- The check SHALL fail, with each finding on its own line and a non-zero exit,
  on: any table, text box, multi-column section, tab character, or page header
  or footer content; a contact field or email or profile link missing; a role
  header that isn't directly after its title line, a date range not attached to
  a company, or a role header count that differs between the two extractions;
  a year before the cutoff when the cutoff was used; and third-person
  pronouns (he, his, him, himself, she, her, hers, herself). It SHALL warn,
  without failing, on a short list of filler phrases.
- `qv check-export <file.docx>` SHALL run the check, and `qv export --style
  resume --format docx` and the desktop resume export SHALL run it on the file
  they write. It SHALL refuse a DOCX part whose declared size is over 10 MB
  before reading it.
- Page count: a PDF resume's page count (from ReportLab) is shown on export.
  The DOCX check reports word and paragraph counts only, because a DOCX isn't
  rendered here and has no reliable page count. Left as is: a DOCX page count.

### 5.5 AI narrative

**R11 — Explicit, user-triggered generation.** **Built.**
- The system SHALL generate a narrative only WHEN the user runs
  `qv export --narrative` or presses "Generate Narrative" in the desktop app.
- The system SHALL NOT make any other outbound network call. The browser
  app fetches only its own static files from its own site (R27).

**R12 — Provider choice and extensibility.** **Built.**
- The system SHALL support Anthropic, OpenAI, Gemini, and Ollama through one
  registry. Adding a provider SHALL require changes only in
  `questvector/core/llm.py`.
- WHEN the user configures a provider, THEN the system SHALL show its setup
  link and any caveat before asking for a key.

**R13 — Show what leaves the machine.** **Planned** (backlog item 1).
- WHEN a remote provider is selected, THEN before sending, the system SHALL
  show the user exactly what dossier and job-description text will be sent
  and to which provider, and SHALL send nothing unless the user confirms.

**R14 — Accuracy guardrails.** **Built.**
- The narrative prompt SHALL instruct the model to output one first-person
  summary paragraph only, to use only facts in the supplied dossier text, to
  add no titles, metrics, numbers, dates, durations, employers, or
  technologies, and to make no depth claim the text doesn't make.
- The system SHALL check every generated summary before it is shown or
  exported. It SHALL strip anything after the summary paragraph (a second
  paragraph, a rule, an italic or bracketed note) and a heading or preamble
  before it, and tell the user what was removed.
- The system SHALL flag, without blocking, narrative sentences containing
  numbers, capitalized names or technology terms, or depth words that don't
  appear in the dossier text that was sent, and third-person pronouns. Flags
  appear in `qv export` output, `qv export --json` and the desktop result, and
  SHALL NOT appear in the exported file (ADR-0032).

**R15 — Live provider testing at no cost.** **Partly built.**
- The test suite SHALL include opt-in live tests, skipped by default, for at
  least one remote provider at no extra cost (a free tier or already-paid
  API credits) and for a local Ollama model.
- Live tests against remote providers SHALL use synthetic data only, and
  SHALL never print, log, or report the API key.
- Built: the local Ollama live test (`tests/test_ollama_live.py`), on
  synthetic data, skipped unless `QV_OLLAMA_LIVE=1`.
- Built: the remote-provider live test (`tests/test_remote_live.py`), on the
  same synthetic data, skipped unless `QV_LIVE_PROVIDERS` names the
  provider. It supports Anthropic, OpenAI and Gemini.
- Done (backlog item 8): the owner's live run against Anthropic
  (`claude-sonnet-5-5`, synthetic data, included API credits) passed on
  5 Nov 2026.
- Planned: a live run against Gemini on Google AI Studio's free tier.

### 5.6 Vault

**R16 — Encrypted storage.** **Built.**
- The system SHALL store provider settings and keys only in the encrypted
  vault, never in plain-text config files.
- Check: **Built** (backlog item 13). `tests/test_secrets_never_leak.py`
  confirms API keys and the passphrase never appear in command output,
  error messages, logs, exported bundles, or the vault file's bytes.
- A wrong passphrase or tampered file SHALL produce a clear error, never
  garbage output.

**R17 — Stronger key derivation.** **Built** (backlog item 13,
[ADR-0015](decisions/0015-pbkdf2-1m-iterations-vault-v2.md)).
- Key derivation SHALL use PBKDF2-HMAC-SHA256 at no fewer than 600,000
  iterations (OWASP minimum); new vaults use 1,000,000. Vault files record
  and authenticate their key-derivation settings.
- Existing vaults SHALL open and be re-encrypted with the new settings on
  next save, without the user re-entering keys.

### 5.7 Desktop app

**R18 — Safe bridge.** **Built.**
- Every desktop bridge method SHALL return `{"ok": true, "data": ...}` or
  `{"ok": false, "error": "..."}` and SHALL NOT raise to the interface.
- The window SHALL show dossier, template and error text as text, never as
  markup, and its page SHALL set a Content-Security-Policy that allows no
  inline script, no inline style and no network connections (ADR-0029).

**R19 — Interface testing.** **Planned** (backlog items 4, 6).
- Automated browser tests (for example Playwright) SHALL cover each desktop
  tab's main path: open a workspace, run a match, validate a template, export,
  and configure a provider.

### 5.8 Repository and CI

**R20 — Pull request checks.** **Partly built.**
- Built: template validation (R7).
- Planned (backlog items 2, 4, 6): WHEN a pull request is opened or updated,
  THEN CI SHALL run tests with coverage, lint (ruff), type checks (mypy),
  static analysis (Semgrep or CodeQL), secret scanning, and a dependency audit
  (pip-audit).
- Planned: every third-party action SHALL be pinned to a commit SHA, and
  workflows SHALL default to read-only permissions.
- Planned: IF any required check fails, THEN the pull request SHALL be
  blocked from merging into `main`.

**R21 — Records kept current.** **Built** (15 Oct 2026).
- Every merged change to behavior, packaging, CI, or documentation SHALL add a
  `CHANGELOG.md` entry, and every significant design choice SHALL get a record
  in `docs/decisions/`.

**R29 — Weekly retired-model check.** **Built** (26 Nov 2026).
- WHEN the weekly scheduled run, or a manual run, of `model-check-weekly.yml`
  finds a default remote model in `questvector/core/llm.py` listed as
  deprecated or shut down on its provider's deprecation page, THEN it SHALL
  open or update one GitHub issue naming the model, the date the page gives and
  the source link, and fail the run.
- IF a page can't be fetched or its structure isn't recognised, THEN it SHALL
  open or update a separate issue and fail the run, and SHALL NOT report the
  default as clear.
- The check SHALL run in CI only, with no API keys; the app SHALL make no new
  network call ([ADR-0001](decisions/0001-local-only-distribution.md),
  [ADR-0031](decisions/0031-weekly-default-model-check.md)).

### 5.9 Browser app

The browser app follows [ADR-0016](decisions/0016-browser-app-static-pages.md)
and is built under backlog item 16. The figures below come from the
browser/Pyodide spike
([`docs/spikes/2026-10-browser-pyodide.md`](spikes/2026-10-browser-pyodide.md)).

**R22 — Core in a Web Worker.** **Planned** (backlog item 16).
- The browser app SHALL run the unmodified QuestVector Python core in
  Pyodide, inside a Web Worker, so starting Python and running the core
  never freeze the page.
- For the same dossier, job description and template, the browser app SHALL
  give the same scores as the desktop app (R4).

**R23 — Files and browser storage.** **Planned** (backlog item 16).
- WHERE the browser supports the File System Access API (Chrome; Edge
  expected but not yet tested), the app SHALL let the user open a folder and
  read and write the dossier there.
- WHERE it doesn't (Safari, Firefox), the app SHALL let the user upload
  dossier files, keep them in browser-private storage, and download them
  again.
- The app SHALL request persistent storage (`navigator.storage.persist()`).
  It SHALL tell the user plainly when data lives only in the browser, and
  SHALL prompt them to download a backup.
- The dossier SHALL stay plain Markdown and SHALL NOT be encrypted in
  browser storage, as on the desktop (G2).

**R24 — Vault with WebCrypto.** **Planned** (backlog item 16, phase f).
- The browser app SHALL use WebCrypto for vault key derivation
  (PBKDF2-HMAC-SHA256) and encryption (AES-256-GCM). It SHALL use the same
  vault file format as the desktop app (format 2, R17), so one vault file
  works in both.
- The browser vault is built when AI arrives in the browser app (R28), since
  until then it has no keys to hold.

**R25 — Load export libraries on demand.** **Planned** (backlog item 16).
- The libraries needed only for export (reportlab, python-docx, lxml,
  Pillow; about 5.4 MB) SHALL load only when the user first exports.

**R26 — Strict Content Security Policy.** **Planned** (backlog item 16).
- Every page SHALL carry the strict CSP from the spike, plus
  `worker-src 'self'`, in a `<meta>` tag, because GitHub Pages can't set
  headers.
- The CSP SHALL hold with no violations and SHALL NOT allow `'unsafe-eval'`.
- WHEN the app is loaded inside a frame, THEN it SHALL refuse to render.
  This is a guardrail, not a control (ADR-0016).

**R27 — Pinned, self-hosted assets.** **Planned** (backlog item 16).
- Pyodide and every wheel SHALL be served from the app's own site, pinned to
  exact versions, and checked against known hashes when the site is built.
- The app SHALL load no third-party scripts and SHALL send no analytics or
  telemetry.

**R28 — No AI in the first browser version.** **Planned** (backlog item 16,
phase f).
- The first browser version SHALL offer no narrative generation.
- AI comes to the browser app only after live provider testing (backlog
  item 8), through a browser transport added via the provider registry
  (R12).

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Privacy | No telemetry, accounts, or backend. The only hosted component is the browser app's static Pages site, which collects no data (ADR-0016, R27). Dossier files stay plain Markdown the user can read and edit without QuestVector. Remote AI calls only on explicit request (R11, R13). |
| Security | Secrets only in the encrypted vault (R16, R17). No secrets in the repository, logs, or bundles. Dependencies audited in CI (R20). |
| Cost | $0: no paid API is required for any feature; Ollama is a complete alternative (G5). |
| Accuracy | Generated text is traceable to the dossier (G4, R14). Public descriptions of the project match what has actually been tested. |
| Portability | Python 3.14 on macOS, Windows, and Linux ([ADR-0013](decisions/0013-python-3-14-uv-lock.md)). The CLI needs no display; the desktop app needs pywebview's platform dependencies. The browser app targets current desktop Chrome, Safari and Firefox, and Edge (expected but not yet tested) (G8); mobile is untested and not a goal yet. |
| Maintainability | Full type hints; mypy and lint clean; Google-style docstrings on public code; one exception hierarchy with no bare `except:`; standard library first. |
| Testability | Every module testable without a network, display, or API key. Coverage target to be set under backlog item 4. |
| Accessibility | Desktop app usable by keyboard with visible focus; color never the only signal of match status. |

## 7. Definition of done for the first full (non-pre-release) release

1. Every requirement marked Planned for backlog items 1, 4, 5, 8, 9, and 13 is
   built, or deferred in writing with its reason.
2. All CI checks green on `main`; required checks enforced by branch
   protection.
3. Narrative generation run end to end with a real local Ollama model and at
   least one remote provider at no extra cost (a free tier or already-paid
   API credits); results recorded.
4. README, spec, PRD, and `CHANGELOG.md` agree, and "never been tested"
   wording is replaced per backlog item 1's exit condition.
5. The owner has run a full cycle with their own dossier: launch, match,
   export, review the bundle.

## 8. Open questions

- Which free-tier remote provider to use for live tests, and whether its
  terms allow test use (backlog item 8).
- Which local model gives the most accurate summaries on the owner's
  hardware (backlog item 9).
- Whether the legacy template-schema path is still needed (backlog item 1).
- Whether to add `MASTER_DEVELOPER_SPEC.pdf` to the repo, or re-point code
  citations to `docs/QuestVector_Spec.pdf` (backlog item 1).
- Coverage target and which checks are required versus advisory (backlog
  items 2, 4).
- Whether ATS rules (R9) should be fixed defaults or template-controlled
  settings.

## 9. Out of scope (candidates for later)

Cover-letter generation; job-fit reads beyond the G-Force
score; semantic matching; importing resumes or LinkedIn profiles into the
dossier; application tracking; a packaged installer.
