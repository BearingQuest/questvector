# 0024. AGENTS.md holds the agent rules, and the shared settings add a sandbox

- **Status:** Accepted
- **Date:** 2026-11-15

## Context
ADR-0019 put the human gates in `.claude/settings.json` as deny and ask
rules, with the rules themselves written in `CLAUDE.md`. Those rules match
command text, so they are a guardrail, not a sandbox, and they did not cover
reading the owner's real workspace, credentials or `.env` files, or what a
sandboxed command may write or reach over the network.

The owner's `project-template` repository (the baseline every BearingQuest
project starts from) now has the fuller version: the rules in `AGENTS.md`,
which other agent tools also read, a `CLAUDE.md` that only imports it, and
settings with more deny and ask rules, Read and Edit denies, and a
`sandbox` block. This is Phase 2 PR D of bringing QuestVector to that baseline
(audit items AGENT-01 to AGENT-08).

Options considered:
- **A. Adopt the template's layout and settings, keep every QuestVector rule.**
- **B. Leave `CLAUDE.md` as the rules file and add only the sandbox.** Two
  places would then describe the rules, and other agent tools would not read them.
- **C. Copy the template wholesale.** It would drop `gh pr review` (ADR-0019 denies
  it) and the option-first release denies, which the template's rules don't cover.

## Decision
Option A.
- `AGENTS.md` is the rules file: every rule from `CLAUDE.md`, plus the human-gates
  list, the untrusted-input rule, never reading `~/career-workspace`, running every
  `gh` command on its own, and the sandbox-safe zizmor command. `CLAUDE.md` is
  `@AGENTS.md` plus the context-and-usage block.
- `.claude/settings.json` is the template's file plus every deny and ask rule
  ADR-0019 had that the template lacks (`gh pr review`, the option-first release
  forms). Each old `:*` rule is now a pair, the bare command and the ` *` form, so the
  no-argument case stays blocked; a test requires the pair for every ` *` rule.
  It adds Read denies (credentials, `~/career-workspace`, `.env`), Edit denies on
  the settings files, and a sandbox: enabled, `failIfUnavailable`, no unsandboxed
  commands, no auto-allow, read and write denies, `~/.cache/uv` writable, and the
  hosts the project needs listed.
- `gh` is the only command excluded from the sandbox (`excludedCommands: ["gh *"]`),
  because inside it `gh` cannot read its login in `~/.config/gh`. Only a plain `gh` call
  matches the exclusion, hence the rule to run each one alone.
- `sandbox.network.strictAllowlist` is not in the file; it takes effect only from user
  or managed settings. The owner sets it in managed settings
  (`/Library/Application Support/ClaudeCode/managed-settings.json`), so the file's
  `allowedDomains` is the record of the hosts the project needs.
- `tests/test_claude_settings.py` replaces `tests/test_agent_rules.py` (one file for
  one settings file): every deny, ask, Read and Edit rule, the mode locks, the exact
  sandbox lists, no allow rules, the pair rule, the `gh` and `~/career-workspace`
  wording in `AGENTS.md`, and that `CLAUDE.md` imports it.
- The review workflow's prompt names `AGENTS.md`. It keeps its sandbox override: the
  runner has no bubblewrap, and the reviewer has no Bash.

## Consequences
- An excluded `gh` has no filesystem or network limit; only the text rules limit it.
  The GitHub rulesets stay the real enforcement for merges, pushes to `main` and tags.
- The sandbox changes what commands can reach. If a legitimate command fails inside it,
  the owner decides whether to widen the file; agents don't edit it.
- Option-first forms are denied only for the four release subcommands ADR-0019 listed,
  not `gh * release *`, which would block any `gh` call whose text mentions a release.
- Supersedes ADR-0019's statement that the rules live in `CLAUDE.md`; its deny and ask
  decisions stand.
- Revisit when the template's settings change or the gates change.
