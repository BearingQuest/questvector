# 0025. Meets engineering baseline 2.0

- **Status:** Accepted
- **Date:** 2026-11-15

## Context
The owner's engineering baseline 2.0 is the standard every BearingQuest
project is audited against. QuestVector was audited twice on 15 Nov 2026: a
first run at commit `ab6a18b`, and a re-run at `e7e6104` after the first round
of fixes (36 PASS, 10 FAIL, 5 DEPARTURE, 8 N/A). The fixes were these pull
requests:

- #40: CI: zizmor, draft-only releases, uvx Semgrep
- #41: opentelemetry-api CVE lock fix
- #42: daily pip-audit, Scorecard and Claude review
- #43: ruff format
- #44: ruff, strict mypy, Makefile, hooks and SBOM
- #45: AGENTS.md and sandboxed settings
- #46: repo gates and requirement IDs (REPO-02, REPO-05, REPO-07, REPO-08)

The owner fixed GH-01 in the shared settings. This pull request closes the
remaining documentation rows: DOC-01 (`SECURITY.md` supported versions),
DOC-06 (README Configuration table, with `tests/test_readme_configuration.py`
keeping it in line with the code), UI-04 (`docs/design.md` no longer claims a
contrast test exists), DOC-08 (the history scan below) and DOC-03 (this
record).

## Decision
QuestVector is recorded as meeting baseline 2.0, with the departures below.
Each is a deliberate choice, not an open finding, and is recorded where shown.

| Row | Departure | Recorded in |
|---|---|---|
| REPO-02 | No `e2e` Makefile target, because there is no end-to-end (Playwright) suite yet. | ADR-0023; this record |
| REPO-03 | `T201` (print) is ignored for `questvector/cli.py` and `tests/live_narrative.py`, which print by design; `spikes/` is excluded from ruff. | `pyproject.toml`; ADR-0023 |
| CI-01 | The required checks keep their eight existing names; there is no single `check` job. | ADR-0021; ADR-0023; `.github/rulesets/main.json` |
| CI-16 | `release.yml` attests with `actions/attest` instead of `actions/attest-build-provenance`. The latter is a wrapper over `actions/attest`, and its README points new workflows to `actions/attest`. Releases are draft-only; the owner publishes. | ADR-0014; ADR-0020 |
| UI-02 | Fonts aren't self-hosted from pinned releases or hash-checked by a test yet. | `docs/design.md`; backlog item 15 |
| UI-03 | Logo SVGs live in `docs/design/logo/` only; they aren't served as static files or hash-checked yet. | `docs/design.md`; backlog item 15 |
| UI-04 (rest) | The CSS is hand-written with no test against `tokens.json`, and there is no strict CSP yet. | `docs/design.md`; backlog item 15 |

UI-02 to UI-04 stay open until the UI redesign (backlog item 15). The owner
decided this on 15 Nov 2026.

**History scan (DOC-08).** On 2026-11-15, gitleaks 8.30.1 ran
`gitleaks git --redact --log-opts="--all" .` over the full history of
`chore/baseline-docs` (branched from `origin/main` at `e021b97`). It reported
**no leaks**. gitleaks reported 67 commits scanned; `git rev-list --count
--all` counts 77 commits. The gap was not investigated further, so the count
is gitleaks's own.

## Consequences
- The baseline status is traceable: an audit row is either closed by a pull
  request listed above or is a departure in the table.
- Closing a departure (for example UI-04 when the contrast test lands) means
  a new record that supersedes this row, not editing this one.
- Revisit when baseline 2.0 changes, when backlog item 15 starts, and when a
  Playwright suite is added (REPO-02).
