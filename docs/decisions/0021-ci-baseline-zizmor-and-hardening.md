# 0021. CI baseline: zizmor, uvx Semgrep, commented permissions, no release cache

- **Status:** Accepted; amends [0011](0011-github-security-baseline.md)
- **Date:** 2026-11-15

## Context
The Phase 1 audit of `ab6a18b` against the project template's CI baseline
found the gaps below. Each change is the template's piece, adapted.

## Decision
- **CI-01, CI-12: zizmor.** A `zizmor` job in `security.yml` runs
  `uvx --exclude-newer 2026-11-03 zizmor@1.32.0 .github` and fails on any
  finding. It is added to the required checks in `main.json`, and
  `strict_required_status_checks_policy` is now `true`. Required checks (8):
  `pytest (full, Python 3.14)`, `pytest (minimal, Python 3.14)`,
  `mypy and pyflakes`, `Validate mission templates`, `gitleaks`, `semgrep`,
  `pip-audit`, `zizmor`.
- **CI-01 departure from the template:** the seven existing check names are
  kept, there is no single `check` job, and there is no `ci.yml`; the checks
  stay in `tests.yml`, `security.yml` and `template-validation.yml`. Renaming
  them would break the required-check contract of 0011 for no gain.
- **CI-16: release workflow.** `setup-uv` has `enable-cache: false` (a poisoned
  cache must not reach a release build; zizmor `cache-poisoning`, high). The
  build/release split already existed. Publishing is the owner's step, see
  [0020](0020-owner-publishes-releases.md).
- **CI-03: permissions.** Every grant above the workflow's `contents: read`
  has a one-line comment, and `contents: read` in a job block that has other
  grants is commented as replacing the workflow grant. A job block that is only
  `contents: read` is redundant and removed.
- **CI-15: Semgrep.** Runs as `uvx --exclude-newer 2026-10-30 semgrep@1.183.0`
  instead of the pinned container (was 1.179.0). Same `p/default` rules and
  same failure behaviour (`--error`, SARIF uploaded under `always()`). The rule
  pack is fetched at run time, so results can change without a code change.
- **Tag ruleset:** `tags.json` becomes `release-tags.json`, see 0020.
- **`${{ }}` in `run`:** `tests.yml` passes `matrix.profile` through a
  step-level `PROFILE` env variable; a test forbids expressions in `run` in
  every workflow.

**Findings hidden by zizmor's default persona** (`--persona auditor`, 1.32.0,
six, all low):
- 3x `undocumented-permissions` (release job writes; gitleaks and semgrep
  `security-events: write`): fixed by the comments above.
- 2x `template-injection` (`${{ matrix.profile }}` in `tests.yml`): fixed by the
  `PROFILE` env variable.
- 1x `concurrency-limits` (`template-validation.yml` has no concurrency group):
  **accepted.** The run takes under a minute, a superseded run only costs
  runner time, and nothing it does is harmful if it finishes. Adding a group
  would change a required workflow for no benefit.

## Consequences
- The `main` ruleset file and the live ruleset differ until the owner applies
  it. Order: this PR's checks pass, the owner applies `main.json` and
  `release-tags.json`, then merges.
- The Semgrep version bump may surface new findings only visible in CI.
- zizmor's version and date are bumped by hand; Dependabot doesn't track them.
