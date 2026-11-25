# 0028. The review comment stops naming a version, and the key file is `~/.qc_post_env`

- **Status:** Accepted
- **Date:** 2026-11-25

## Context
Two small carry-overs (C4 and C5), both from the owner (Dusten, 25 Nov 2026):

- **C4.** The comment above `claude_args` in `claude-review.yml` named the Claude Code
  version the action installs ("the action pins 2.1.323", added in ADR-0026). That number
  goes stale with every claude-code-action bump Dependabot opens.
- **C5.** QuestCast 4.0.0 renamed its key file from `~/.ai_post_env` to `~/.qc_post_env`.
  The engineering baseline's AGENT-04 and AGENT-06 wording changed on 25 Nov 2026 to match,
  and Dusten edited `.claude/settings.json` (the `Read()` deny and the sandbox `denyRead`).

## Decision
**C4.** The comment now says "the action installs the version set by `CLAUDE_CODE_VERSION`
in its base-action/action.yml; check it there when Dependabot updates the action", the
wording project-template uses. It keeps the "Needs Claude Code 2.1.285 or later" floor.
Comment lines only; nothing else in the workflow changes. This replaces the sentence
ADR-0026 recorded about the comment naming 2.1.323.

**C5.** `tests/test_claude_settings.py` requires `Read(~/.qc_post_env)` and
`~/.qc_post_env` in the sandbox `denyRead` list instead of the old name, so the test
guards the settings file as Dusten edited it. Claude did not edit `.claude/settings.json`.
No other file in the repo named the old key file.

## Consequences
The workflow comment can't go stale on a Dependabot bump. If the `Read()` deny or the
sandbox `denyRead` for the key file is dropped or reverted to the old name, the settings
test fails. The `claude-review` check does not run on this pull request, because it
changes the review workflow.
