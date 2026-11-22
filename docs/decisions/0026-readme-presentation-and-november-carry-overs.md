# 0026. README presentation and the November carry-overs

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
Three decisions by the owner reach every repo, and this one needed a small fix:

- the cross-project README standard (Dusten, 15 Nov 2026; `engineering-standards.md`
  "README presentation"), already merged in project-template #12, Risk Trainer #68 and
  QuestCast #36;
- three carry-overs (Dusten, 19-20 Nov 2026): five `AGENTS.md` rules, the uv install
  cooldown as the first key under `[tool.uv]`, and a pin on the Claude review model;
- the README and `docs/DEVELOPMENT.md` gave a hard-coded test count (289) that had gone
  stale (main collects 486).

## Decision
**README presentation.** The emoji title, the two italic banner lines and the two badges
become a centered family header: the Bearing Quest lockup (switching with GitHub's light
or dark theme), the name QuestVector, a one-line description and "Part of the Bearing Quest
project family". Below it: a badge row (Tests status served by GitHub; the OpenSSF
Scorecard badge that `scorecard.yml` publishes; "status: proof of concept"; license and
Python 3.14 as static shields.io badges; the existing PRs-welcome badge); the
proof-of-concept banner, word for word, as a WARNING alert (so the accuracy rule's "README
banner" is now that alert); the tagline in italics; a terminal demo GIF; and a Mermaid
diagram showing everything local, with narrative generation reaching a cloud API only when
asked. Everything from "QuestVector is an open-source" down is unchanged, including the
Configuration table.

The demo GIF is recorded with VHS 0.12.1 from `docs/readme/demo.tape` (`qv launch` and
`qv sync-ast` on the synthetic dossier in `tests/fixtures/live_narrative`, in a throwaway
folder: no network, no vault, no keys, nothing from `~/career-workspace`); the output was
checked against main `6b81fbd` on 22 Nov 2026. VHS (charmbracelet/vhs, MIT) is installed
with Homebrew on the owner's Mac when the demo is re-recorded; it is a tool, not a project
dependency.

`tests/test_readme.py` checks that every image has alt text and comes only from
`docs/readme/` or from github.com (BearingQuest workflow badges), img.shields.io or
api.scorecard.dev; every `<picture>` has an `<img>` fallback; every file in `docs/readme/`
is used and is 5 MB or less; SVGs pass the logo safety rules; the two lockups match their
SHA-256 (unedited design-system copies); and each tape's Output is an existing file in
`docs/readme/`. Its guardrails were mutation-checked by Claude on 15 Nov 2026 in a scratch
copy of the template: 18 mutations, all caught.

**Five `AGENTS.md` rules (Dusten, 19 Nov 2026).** Push with `git push origin <branch>`,
never `-u`; pty tests skip outside CI; browser-starting scripts are run by the owner in a
plain Terminal; no `sandbox.network.allowLocalBinding` unless tests start a local server;
and a plan says when a baseline re-audit is due. All are already true here: no test needs a
pty, no test starts a local server, and `.claude/settings.json` has no `allowLocalBinding`.
`tests/test_claude_settings.py` keeps each rule in place.

**Install cooldown first (Dusten, 20 Nov 2026).** `exclude-newer = "7 days"` is now the
first key under `[tool.uv]`, above `required-version`. Semgrep reads the table only up to
the first bracket, and the standard requires the cooldown first. Nothing moved in
`uv.lock` (`uv lock --check` and `uv sync --locked --all-extras` ran clean, the lock still
records `exclude-newer-span = "P7D"`), and `make audit` found no known vulnerabilities.
This amends ADR-0013's placement of the setting only. A new `AGENTS.md` rule keeps it first
and never loosened; tests in `tests/test_tooling_config.py` check the order, the value and
the lock's span.

**Review model pin (Dusten, 20 Nov 2026).** `claude-review.yml` passes
`--model claude-sonnet-5-5`, an exact model ID, not an alias. The review model changes only
through a reviewed pull request; another Claude model gives a different reviewer, not an
independent one. The comment now names Claude Code 2.1.323, which claude-code-action
v1.0.275 installs (Dependabot #48). The claude-review check does not run on this pull
request, because it changes the review workflow.

**Test count.** The hard-coded count is dropped from `README.md` and `docs/DEVELOPMENT.md`
so it can't go stale again; the pull request body reports the count this branch collects.

**Mutation results for this pull request.** Each ran in a scratch copy and failed a test:
deleting each of the six new `AGENTS.md` rules (the five and the cooldown rule); moving
`exclude-newer` below `required-version`; putting `[` in the comment above it; changing
"7 days" to "1 day"; deleting the span line from `uv.lock`; deleting `--model`; changing it
to the alias `sonnet`. 12 of 12 caught.

## Consequences
The README matches the family look and is checked by a test, so images can't drift or pull
from new hosts unnoticed. Re-recording the demo needs VHS on the owner's Mac. The README
test-count line can no longer go stale. Changing the review model needs a pull request
that edits the pin and its test. If a security fix is newer than 7 days, the route is a
per-package `exclude-newer-package` override and a decisions row, decided by the owner.
