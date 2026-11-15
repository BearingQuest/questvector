# 0022. Daily pip-audit, OpenSSF Scorecard and Claude review workflows

- **Status:** Accepted; supersedes the "AI review workflow" decision in
  [0011](0011-github-security-baseline.md) and extends
  [0021](0021-ci-baseline-zizmor-and-hardening.md)
- **Date:** 2026-11-15

## Context
Phase 2 of the CI baseline copies the remaining pieces of
`BearingQuest/project-template` (checked at its `origin/main`, `119ca6c`).
ADR-0011 left out a Claude review workflow ("left out for now"). The owner
decided on 15 Nov 2026 to add it. Four audit items, each adapted:
- **CI-10:** a daily pip-audit of `uv.lock` on `main`.
- **CI-11:** OpenSSF Scorecard analysis.
- **CI-13:** a Claude review of each pull request.
- **CI-14:** Dependabot compared with the template's.

## Decision
- **`pip-audit-daily.yml` (CI-10).** Runs at 07:23 UTC every day and on
  `workflow_dispatch`, never on pull requests, with a `contents: read` token.
  Its export and audit commands are character-for-character those of the
  `pip-audit` job in `security.yml` (every package in `uv.lock`, all extras
  and groups, `--strict --disable-pip --no-deps`); a test compares the two so
  they can't drift. The template's version audits a plain export, which this
  repo's lock (platform markers, the `audit` group) can't use. Unlike the
  required job, it runs `setup-uv` with `enable-cache: false`: a once-a-day
  job gains nothing from a cache, and off removes a cache-poisoning path. Job
  name `pip-audit (daily)`. This is the daily half of backlog item 18.
- **`scorecard.yml` (CI-11).** Weekly (Wednesday 04:23 UTC) and on push to
  `main`. Workflow permissions `{}`; the one job holds `security-events`,
  `id-token`, `contents` and `actions`, each with a reason comment. Scorecard's
  publishing rules apply (no `run` steps, approved actions only). Results go
  to scorecard.dev and to code scanning under the category `scorecard`. No
  README badge until a first run has published.
- **`claude-review.yml` (CI-13).** Runs on pull requests, skipped for
  Dependabot, forks and drafts. The job has `contents`, `pull-requests` and
  `issues` read plus `id-token: write`, which `claude-code-action` needs to
  exchange an OIDC token for the Claude GitHub App token; nothing in it can
  write to the repository. The reviewer's only tool is the inline-comment tool
  (no Bash), and the prompt says the pull request's text is untrusted data.
  Authentication is a reference to the `CLAUDE_CODE_OAUTH_TOKEN` secret; no
  key is in the repo. The prompt names `CLAUDE.md` for now and moves to
  `AGENTS.md` with Phase 2 PR D.
- **Sandbox override.** `claude_args` keeps `--settings
  '{"sandbox":{"enabled":false}}'`. The runner has no bubblewrap or socat, and
  this repo's sandbox settings arrive in a later pull request with
  `failIfUnavailable`, which would abort the review at start. The command-line
  setting outranks the project file and only turns the sandbox off for this run;
  the sandbox wraps only Bash, which the reviewer doesn't have, and every deny
  rule still applies. A test pins the override and the single tool.
- **First run.** `claude-code-action` refuses to run when the workflow file
  differs from the one on `main`, so the review can't run on the pull request
  that adds it. The next pull request is the proof.
- **Not required checks.** None of the three is in `main.json`, which doesn't
  change: nothing to re-apply. A test keeps their job names out of the required
  set. The job `review` runs on pull requests but is advisory only.
- **Token rules, tested.** `permissions: {}` at workflow level is allowed for
  exactly `scorecard.yml` and `claude-review.yml` (every other workflow stays
  `contents: read`); `id-token: write` may appear only on the Scorecard
  `analysis` job, the review job and the release job, each with a comment.
- **Dependabot (CI-14).** Compared with the template's file: ecosystems (`uv`,
  `github-actions`), directory, weekly schedule, 7-day cooldown, limit of 5
  and minor/patch grouping are identical, and no earlier decision here says
  otherwise. Only a comment was added: the gitleaks, zizmor and Semgrep
  versions in `security.yml` are bumped by hand.
- **Scorecard's `upload-sarif` pin.** `scorecard.yml` uses the template's
  `github/codeql-action/upload-sarif` v4.39.3; `security.yml` is on v4.39.2
  and Dependabot will bring it forward. The template's test requiring the two to
  match is not ported.
- **ADR-0001.** All three are CI only. The app makes no new network call;
  the workflows' network use is scorecard.dev and, for the review, Anthropic's
  API from the GitHub runner.

**zizmor:** zero findings at the default persona, no inline suppression. The
`auditor` persona reports one medium finding, `secrets-outside-env`, on the
review's `CLAUDE_CODE_OAUTH_TOKEN` reference. **Accepted:** an environment
with required reviewers would block every review run, the token is an
organization secret used only by this workflow, and the job cannot write to
the repository.

## Consequences
- A new advisory against a locked version fails a scheduled run (GitHub
  emails the owner) before an unrelated pull request hits it. GitHub turns
  off scheduled workflows after 60 days without repository activity; they
  must then be re-enabled by hand.
- Review comments are advice: nothing blocks a merge, and human review stays
  the owner's. The review costs subscription usage on every non-draft pull
  request push; revisit if that is too much.
- The org secret's visibility to this repository, and the repository being
  public (Scorecard publishing), are settings outside this change and were not
  verified when it was written.
- Until Phase 2 PR D, the review prompt names `CLAUDE.md`.
