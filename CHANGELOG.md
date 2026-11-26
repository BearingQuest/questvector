# Changelog

All notable changes to QuestVector are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). The version number lives in one
place, `questvector/__init__.py` (`__version__`).

**Keeping it current:** every pull request that changes behavior, packaging,
CI, or documentation adds a line under `[Unreleased]`. On release, rename
`[Unreleased]` to the new version and date, bump `__version__` to match, and
start a fresh `[Unreleased]` section. Significant design choices also get a
record in [`docs/decisions/`](docs/decisions/).

## [Unreleased]

### Added
- Weekly check for retired default models ([ADR-0031](docs/decisions/0031-weekly-default-model-check.md), PRD R29, backlog item 18): `model-check-weekly.yml` (Mondays and on demand, never on pull requests, not a required check) runs `scripts/check_default_models.py`, which reads each remote provider's deprecation page and opens or updates one GitHub issue when a default in `questvector/core/llm.py` is deprecated or shut down, or when a page can't be read; the run then fails. Standard library only, no API keys, CI only: the app makes no new network call. `mypy` now checks `scripts/` too.

### Changed
- Docs: the `gh attestation verify --repo BearingQuest/questvector` steps in the README and `docs/DEVELOPMENT.md` are confirmed (verified on the v1.2.0 wheel, sdist and SBOM, 26 Nov 2026), so "unconfirmed" is gone; `SECURITY.md` names 1.2.0 as the supported release and links the private-report page directly; `AGENTS.md` and `docs/DEVELOPMENT.md` list the new workflow as not required.

## [1.2.0] - 2026-11-26

**Vault upgrade:** a vault saved by this version can't be opened by QuestVector 1.1.0 or earlier. Older vaults still open and are upgraded the next time they are saved. ([ADR-0015](docs/decisions/0015-pbkdf2-1m-iterations-vault-v2.md))

**Highlights**
- Better matching ([ADR-0027](docs/decisions/0027-keyword-normalization.md)): "CI/CD", "SOC 2", "ISO 27001", "K8s" and "on call" match one form; a keyword at the end of a sentence now matches; role titles in Chronology headings count. Scores for existing dossiers can rise.
- Clearer results ([ADR-0030](docs/decisions/0030-negation-warnings-and-asked-keyword-counts.md)): "N of M template keywords in this posting are in your dossier" next to the score, "N of M asked" per category, and a list of dossier lines that negate a skill the match still counted. The desktop window now shows weak categories. Scores and the formula are unchanged.
- Stronger vault ([ADR-0015](docs/decisions/0015-pbkdf2-1m-iterations-vault-v2.md)): PBKDF2-HMAC-SHA256 at 1,000,000 iterations, file format 2 and atomic owner-only saves. A vault saved by this version can't be opened by 1.1.0 or earlier.
- Safer desktop window ([ADR-0029](docs/decisions/0029-desktop-text-only-csp-bundle-names.md)): data is shown as text, the page has a Content-Security-Policy, and a bundle name can't write outside `bundles/`.
- AI providers: default models updated (checked 4 Nov 2026); a clear error when a provider doesn't recognize a model; API keys redacted from SDK error messages. Narrative generation has been tested live with Ollama and Anthropic on synthetic data; OpenAI and Gemini are tested with simulated responses only.
- Release files: a CycloneDX SBOM ships with the wheel and sdist and is attested with them ([ADR-0023](docs/decisions/0023-ruff-strict-mypy-make-hooks-sbom.md)); the workflow now creates a draft and the owner publishes ([ADR-0020](docs/decisions/0020-owner-publishes-releases.md)).
- Compatibility: a custom mission template keyword that is several words with no alias, a common word, or a single letter now fails to load with a message naming it. Such keywords could never match before.
- Dependency security fixes: pyasn1 0.6.5 and opentelemetry-api 1.45.2.

### Added
- Matching display, backlog item 1 part 2 ([ADR-0030](docs/decisions/0030-negation-warnings-and-asked-keyword-counts.md)); the score, alert level and formula are unchanged. **Asked-keyword counts:** "N of M template keywords in this posting are in your dossier" next to the score and "N of M asked" (or "not asked") per category, in `qv sync-ast`, `--json` (new keys `matched_count`, `asked_count`, `counts_text`, `negation_warnings`, and per category `matched_count`, `asked_count`, `counts_text`; every existing key is unchanged), the desktop window, and PDF and DOCX exports. **Negation warnings:** `qv sync-ast` and the desktop window list dossier lines where no, not, never, without, none or "training only" sits next to a keyword that matched (not in exports). The README says to leave out statements of what you haven't done, and explains the counts. The two known-limitation tests now assert the warnings and the asked counts, and `tests/export_text.py` is the one shared reader of export text.
- Two carry-overs ([ADR-0028](docs/decisions/0028-review-comment-version-and-qc-post-env.md)): the comment in `claude-review.yml` no longer names the Claude Code version the action installs (it went stale with every claude-code-action bump) and says where to check it; `tests/test_claude_settings.py` requires `~/.qc_post_env`, the key file's new name, in the `Read()` deny and sandbox `denyRead` lists, matching the settings file Dusten edited. CI and tests only.
- Backlog item 20: README screenshots of the GUI, alongside the CLI demo, once the GUI is usable. Docs only.
- Keyword normalization ([ADR-0027](docs/decisions/0027-keyword-normalization.md), `questvector/core/normalize.py`): job-description text, dossier text and template keywords are reduced the same way, so "CI/CD", "CI-CD", "SOC 2", "ISO 27001", "K8s", "on call", "TCP/IP", "cloud-native", "PCI-DSS" and "infrastructure as code" meet the template forms `cicd`, `soc2`, `iso27001`, `kubernetes`, `oncall`, `tcpip`, `cloudnative`, `pci` and `iac`. A template keyword that isn't exactly one word after normalization is now a validation error naming the template and the keyword; duplicates collapse; the boilerplate template's placeholder keywords ("Primary Skill 1" and so on, which could never match) are now single words, in `templates/boilerplate.qv-mission.yaml` and `CONTRIBUTING_TEMPLATES.md`. Characterization tests pin two known limitations kept open in backlog item 1: a negated skill still counts as a match, and a large dossier scores 100.0 on any posting.
- README presentation, three carry-overs and a test-count fix ([ADR-0026](docs/decisions/0026-readme-presentation-and-november-carry-overs.md)): the README gains the Bearing Quest family header, a badge row, the proof-of-concept banner as a WARNING alert, a terminal demo GIF and a Mermaid diagram, checked by `tests/test_readme.py`; `AGENTS.md` gains five rules (push without `-u`, pty tests, browser scripts, `allowLocalBinding`, baseline re-audit) and a rule keeping `exclude-newer` the first key under `[tool.uv]`, which now is; `claude-review.yml` pins `--model claude-sonnet-5-5`; the hard-coded test count is gone from the README and `docs/DEVELOPMENT.md`. Nothing moved in `uv.lock`. The app is unchanged.
- Baseline 2.0 docs (audit rows DOC-01, DOC-03, DOC-06, DOC-08, UI-04; [ADR-0025](docs/decisions/0025-meets-engineering-baseline-2-0.md)): `SECURITY.md` now says the latest release and `main` are supported; the README gains a Configuration table of every `config.py` setting and environment variable with its default, kept in line with the code by `tests/test_readme_configuration.py`; `docs/design.md` says the token contrast test is planned with the UI redesign (backlog item 15); ADR-0025 records the baseline, its departures and a clean full-history gitleaks scan (15 Nov 2026). The app is unchanged.
- Repo gates (baseline audit rows REPO-02, REPO-05, REPO-07, REPO-08): `make check` now runs pytest with `--cov=questvector` (the 90% floor) and `qv template validate` on every template under `templates/`; `.gitignore` covers Terraform state and `.terraform/` and loses its duplicate lines; every Built or Partly built PRD requirement is named in a test docstring, enforced by `tests/test_requirements_coverage.py`; the one `# noqa: E501` in `llm.py` is gone (the Ollama request moved into a small `_read_json` helper so the `nosemgrep` comment fits the line limit). The app's behaviour is unchanged.
- Agent rules moved to `AGENTS.md` ([ADR-0024](docs/decisions/0024-agents-md-and-sandboxed-settings.md)); `CLAUDE.md` now imports it. New rules: never read `~/career-workspace`, run every `gh` command on its own, the sandbox-safe zizmor command, a human-gates list and an untrusted-input rule. `.claude/settings.json` gains Read and Edit denies, more deny and ask rules (each old `:*` rule is now a bare plus ` *` pair) and a sandbox (`gh` is the only command excluded from it). `tests/test_agent_rules.py` is merged into `tests/test_claude_settings.py`, which also checks `AGENTS.md` and the `CLAUDE.md` import. `claude-review.yml` names `AGENTS.md` in its prompt (the review can't run on this pull request). The app is unchanged.
- Baseline tooling ([ADR-0023](docs/decisions/0023-ruff-strict-mypy-make-hooks-sbom.md)): ruff 0.17.4 (lint and format check, replacing pyflakes), a `Makefile` (`make check`, `audit`, `sbom`, `hooks`), a pre-push gitleaks hook (`make hooks`, once per clone), `tests/_proc.py` as the one place tests start a process, `.git-blame-ignore-revs` for the formatting commit of #43, and tests that keep each of these in line with CI.
- A CycloneDX SBOM (`sbom.cdx.json`: runtime dependencies and the AI extras) is built by the release workflow, covered by `SHA256SUMS`, attested, and attached to the draft release.
- Three workflows, none a required check ([ADR-0022](docs/decisions/0022-scheduled-audit-scorecard-and-claude-review.md)): `pip-audit-daily.yml` (the same pip-audit export as `security.yml`, every day and on demand, no cache), `scorecard.yml` (OpenSSF Scorecard, weekly and on push to `main`, published to scorecard.dev and code scanning) and `claude-review.yml` (Claude reviews each non-draft pull request with one inline-comment tool and no Bash; keeps `--settings '{"sandbox":{"enabled":false}}'` so it still runs when this repo's sandbox settings land). Supersedes ADR-0011's decision to leave the review out. The review can't run on the pull request that adds it. Tests in `tests/test_workflows.py` (the token guard now allows `permissions: {}` for the Scorecard and review workflows only); `dependabot.yml` gains a comment. `main.json` is unchanged. CI only.
- zizmor workflow audit as a required check (`security.yml`, `zizmor@1.32.0`), and `strict_required_status_checks_policy: true` in `main.json`; the ruleset must be re-applied by the owner ([ADR-0021](docs/decisions/0021-ci-baseline-zizmor-and-hardening.md)). CI only.
- Shared Claude Code settings (`.claude/settings.json`, [ADR-0019](docs/decisions/0019-agent-permission-guardrails.md)): auto and bypass-permissions modes are turned off; `gh pr merge`, `gh pr review`, `git tag`, `gh release create`/`edit`/`delete`/`upload` and `rm -rf` are denied, in both plain and option-first forms (`gh -R x pr merge`); `git push`, `gh pr`, `gh api` and `python3` ask first. No allow rules. A guardrail, not a sandbox: the rules match command text, and only managed settings make the mode settings binding. `tests/test_agent_rules.py` keeps every rule in place. The app is unchanged.
- Opt-in live test of narrative generation against remote providers (`tests/test_remote_live.py`): skipped unless `QV_LIVE_PROVIDERS` names the provider (`anthropic`, `openai`, `gemini`), so CI and the default suite make no network call. The key comes only from the provider's usual variable (`ANTHROPIC_API_KEY` and so on) and is never printed; failures are redacted and shown without a traceback, and an opted-in provider with no key fails clearly. Optional model override per provider (`QV_ANTHROPIC_MODEL` and so on). One call per provider per run, on synthetic data, printing the narrative for scoring by hand. Harness checks run in CI with the provider faked. How-to in `docs/DEVELOPMENT.md`, including reading the key with `read -s` so it stays out of shell history. Run live by the owner on 5 Nov 2026 against Anthropic (`claude-sonnet-5-5`): passed.
- Pull request template: `.github/pull_request_template.md`, the base template from the Personal Software Projects engineering standards (Summary and Requirements), and a line in `CLAUDE.md` telling agents to fill in every section in the PR body, because `gh pr create --body` skips the template. No code or CI change.
- Backlog item 19: attach a CycloneDX 1.5 SBOM of the locked runtime dependencies to each release, generated with `uv export` (experimental in uv; `cyclonedx-py` is the fallback) and covered by `SHA256SUMS` and the build-provenance attestation. Docs only: nothing is built yet.
- Backlog item 18: two scheduled GitHub Actions checks, each its own workflow and pull request, both buildable now that item 8's default-model update has merged (PR #26): a weekly check that reads the three providers' deprecation pages and opens or updates an issue when a default model is deprecated or shut down, or when a page can't be read; and a daily dependency audit that runs the same pip-audit command as the `pip-audit` check, so a new advisory fails a scheduled run before an unrelated pull request hits it. Scheduled and manual runs only, never on pull requests. CI-only: the app makes no new network calls. Cross-referenced with item 8's planned retired-model warning. Docs only.
- Backlog item 17: the base pull request template and the `CLAUDE.md` line are done (owner decision, 12 Nov 2026); tailoring the template for QuestVector (decision records, ADR-0001 check, vault and keys, live AI testing, no deploy section) is the remaining work. Docs only.
- Design pack: a snapshot of the Bearing Quest design base in [`docs/design.md`](docs/design.md) and `docs/design/` (tokens, logo SVGs, the five screen mockups, and the mockups' reference CSS), so UI work no longer depends on the private design-system artifact. Linked from ADR-0017, backlog item 15 and `CLAUDE.md`. Docs only.
- Decision to adopt the Bearing Quest design base for the desktop and browser apps, keeping the Flight Deck instrument-panel motif ([ADR-0017](docs/decisions/0017-bearing-quest-design-base.md)): shared color tokens for light and dark, self-hosted Inter and IBM Plex Mono fonts, the Bearing Quest logo, rules for the accent color and data colors, and a token contrast test. QuestVector's own accent is Horizon blue. Docs only: nothing is built yet.
- Decision to build a browser-only QuestVector ([ADR-0016](docs/decisions/0016-browser-app-static-pages.md)): static files on this repository's GitHub Pages site, running the existing Python core in Pyodide, with data kept in the browser, for users who can't install software. It replaces the planned React/Rust Web Cockpit; the desktop app and CLI continue. The PRD (G8, §5.9 R22–R28), backlog (new item 16; items 14 and 15), README, and spike doc are updated. Docs only: nothing is built yet.
- Spike (experiment, not a feature): can the Python core run in a browser tab through Pyodide? Findings in [`docs/spikes/2026-10-browser-pyodide.md`](docs/spikes/2026-10-browser-pyodide.md); local-only prototype pages in `spikes/browser-pyodide/`. The package, its dependencies, tests, and CI are unchanged.
- Vault file format 2: the key-derivation name, iteration count, and salt are stored in the file and authenticated as AES-GCM associated data, so changing any of them makes decryption fail. Iteration counts outside 600,000–5,000,000 are rejected before any key is derived. Format 1 vaults still open and are rewritten as format 2 on their next save, with no extra prompts; format 1 is never written again, and an unknown version gets a clear error. ([ADR-0015](docs/decisions/0015-pbkdf2-1m-iterations-vault-v2.md))
- `qv vault set-key` asks for the passphrase twice when it creates a new vault, and saves nothing if the two don't match.
- `tests/test_secrets_never_leak.py` (PRD R16): API keys and the passphrase never appear in command output, error messages, logs, exported PDF or DOCX bundles, or the vault file's bytes.
- Format 1 vault fixtures in `tests/fixtures/vault/`, written by the released 1.1.0 code, and a `real_kdf` test marker; other tests run the vault at a low iteration count through a `tests/conftest.py` fixture, so the suite stays fast.

### Changed
- `qv sync-ast --json` and the desktop bridge build their result from one serializer, `MatchResult.to_dict()`, so they can no longer drift. The desktop's result now includes `weak_categories` (PRD R3 already said it shows them).
- Compatibility: a custom mission template keyword that is a common word or one letter (for example "it" or "x") now fails to load and fails `qv template validate`, with an error naming the template, category and keyword. Before, it loaded, but `tokenize()` drops such words, so it could never match. No starter or boilerplate template is affected.
- Backlog item 19 is marked done and its attestation wording is corrected (the wheel, sdist and SBOM are attested; `SHA256SUMS` is not). ADR-0029 says Claude Code did the scratch-copy check, and its dates (and its index row and the backlog line) are 25 Nov 2026, the owner's local date. Docs only.
- Backlog item 1: the negation bullet is done as a warning plus docs (the exclusions section was not built); the saturation display step is done and the formula stays open, with the finding that a category the posting never asks about counts as full coverage.
- Backlog item 1's exit condition is revised (owner decision, 13 Nov 2026): the README drops "proof of concept" after the owner compares QuestVector's output on past applications with materials Claude produced, against criteria written beforehand; the repo records only the method and a summary. Replaces the 15 Oct "real job search" condition. Docs only.
- Compatibility: a custom mission template with a multi-word keyword that maps to no alias now fails to load and fails `qv template validate`, with an error naming the template and keyword. Before this change it loaded, but such a keyword could never match. ([ADR-0027](docs/decisions/0027-keyword-normalization.md))
- Role titles in Chronology headings now count as keywords (Capabilities and Impact headings still don't), so "Engineering Manager" no longer shows `manager` as a gap.
- "SOC 2" no longer matches the `soc` keyword (it now means `soc2`). Scores for existing dossiers can rise, because sentence-final keywords and the new variants now match.
- README: the dossier section no longer asks users to write both "Kubernetes" and "K8s".
- The required check `mypy and pyflakes` is now `ruff and mypy` (ruff check, ruff format --check, mypy); `.github/rulesets/main.json` changes with it and must be re-applied. mypy is now strict for the whole `questvector` package. Lint fixes with no behaviour change: stale `noqa` removed, imports sorted, duplicate stopwords removed, long lines wrapped.
- A Gemini or Ollama reply whose text isn't a string now raises a clear `LLMError` instead of failing on `.strip()`. The Ollama host check (http or https with a host) now has tests for every case.
- Release workflow no longer publishes: it attests, then creates a draft pre-release, and the owner publishes it by hand; `setup-uv` caching is off in it ([ADR-0020](docs/decisions/0020-owner-publishes-releases.md), [ADR-0021](docs/decisions/0021-ci-baseline-zizmor-and-hardening.md)). `docs/DEVELOPMENT.md` Releasing updated.
- `.github/rulesets/tags.json` is now `release-tags.json`: no bypass actors, no creation restriction, `deletion`, `non_fast_forward` and `update` rules (ADR-0020). Owner re-applies it.
- Semgrep runs with `uvx` (1.183.0, `p/default`, same failure behaviour) instead of a container; permission grants in workflows carry comments; `tests.yml` passes `matrix.profile` through `env`. New guards in `tests/test_workflows.py`.
- Docs now point to `BearingQuest/questvector` (README and `docs/DEVELOPMENT.md`: URLs, clone commands, `gh api` paths, release checks). v1.1.0 was signed before the move, so it verifies with `gh attestation verify <file> --owner dustenatx --signer-workflow dustenatx/QuestVector/.github/workflows/release.yml`, not `--repo`; the command for later releases is unconfirmed until the first one is verified.
- README banner and status table: narrative generation is now described as tested live with Ollama (gemma4:12b-it-q4_K_M) and Anthropic (claude-sonnet-5-5, 5 Nov 2026, synthetic data), with OpenAI and Gemini tested with mocks only; still a proof of concept. This meets backlog item 1's exit condition for the README; the spec PDF waits for item 3. Backlog item 8 is done for Anthropic (Gemini's free tier still open); item 5 records the live run's finding that the model appended a note after the summary, which must be stripped or flagged; ADR-0018 and PRD R15 record the result. README test counts updated. `CLAUDE.md`'s public-claims rule now says the README names exactly which providers were tested live and which with mocks only, and PRD release criterion 3 accepts a remote provider at no extra cost (a free tier or already-paid API credits), matching R15.
- The live test fixtures moved from `tests/fixtures/ollama_live/` to `tests/fixtures/live_narrative/`, now shared by the Ollama and remote live tests through a small helper module, `tests/live_narrative.py`. The Ollama live test now prints its narrative for scoring by hand (`-s`). PRD R15 now allows already-paid API credits as well as a free tier, and requires that live tests never print or report the key.
- A model the provider doesn't recognize now gives a clear error for Anthropic, OpenAI and Gemini, naming the provider, the model and the fix (`qv vault set-key --provider <name> --model NAME`), with the provider's own message redacted of the API key. It is detected from each SDK's own error: Anthropic `NotFoundError` with type `not_found_error`, OpenAI `NotFoundError` with code `model_not_found`, and Gemini `ClientError` 404 `NOT_FOUND`. Other errors keep the generic "LLM API call failed" message.
- Anthropic narrative generation switches thinking off (`thinking={"type": "between_tools"}`) for Claude Sonnet 5.5, which otherwise thinks by default and could spend the 600-token limit before answering. It's sent only to the model ids in `ANTHROPIC_THINKING_OFF_MODELS`, so other Claude models get the same request as before. A declined request and a token limit hit before any text now give clear errors. ([ADR-0018](docs/decisions/0018-anthropic-thinking-off.md))
- The `anthropic` SDK minimum is now 2.0 (in `llm-anthropic` and `llm`); `uv.lock` already had 2.2.0. QuestVector's calls needed no change for the 2.x SDK.
- Default remote AI models updated to each provider's recommended replacement, checked 4 Nov 2026 against the official deprecation pages: Anthropic `claude-sonnet-4-5` (retiring 30 Nov 2026) → `claude-sonnet-5-5`; OpenAI `gpt-4o-mini` (shutting down 14 Jan 2027) → `gpt-6-luna`; Gemini `gemini-2.0-flash` (shut down 1 Jun 2026) → `gemini-3.6-flash`. Sources are in `docs/DEVELOPMENT.md`. OpenAI and Gemini are still tested only with mocks. A vault keeps the model it was set up with: run `qv vault set-key --provider <name>` again to store the new default. Backlog item 8 records a possible warning for a retired stored model, not built yet.
- [ADR-0017](docs/decisions/0017-bearing-quest-design-base.md) adds a `caution` token (`#7A4A00` light, `#F2C46B` dark) on `caution-bg` (`#FDF3E0`, `#33291A`) for the "Gaps" match status, and decides the header: the Bearing Quest mark beside the QuestVector name, with no family strip. It also records that Risk Trainer joined the base on a light path and that the repo's `docs/design/` snapshot is what the code uses. Docs only.
- QuestVector's accent is Horizon blue (`qv-accent`: `#1F68A8` light, `#7DB8F0` dark) for the active tab, the selected template and instrument highlights; links and the one call to action per screen stay Bearing Quest orange. Recorded in [ADR-0017](docs/decisions/0017-bearing-quest-design-base.md) and backlog item 15. Docs only.
- Backlog item 15 (UI/UX) is re-planned around ADR-0017: choose and contrast-check QuestVector's accent, then build a screens mockup from the design system before the browser app shell, with one stylesheet for both apps. Item 16 phase (c) points to item 15 for the look.
- Backlog item 15's labeling question is decided: labels stay themed (Sync-AST, G-Force, Vault, mission template), chosen after the screens mockup. Recorded in item 15 and [ADR-0017](docs/decisions/0017-bearing-quest-design-base.md)'s consequences. Docs only.
- Vault key derivation is PBKDF2-HMAC-SHA256 at 1,000,000 iterations (was 390,000; OWASP's minimum is 600,000). Unlock takes about 150 ms on an Apple M3. Argon2id was considered and not chosen.
- Vault saves are atomic: written to an owner-only temporary file in the same folder, flushed, then renamed over the vault, so an interrupted save leaves the previous vault intact. Previously the file was written in place and restricted afterwards.
- A new vault needs a non-empty passphrase (CLI and desktop). Existing vaults with an empty passphrase still open and save.
- Error messages from the Anthropic, OpenAI, and Gemini SDKs have the API key replaced with `[redacted]` before QuestVector shows them.
- `VaultData`'s `repr()` no longer includes the API keys.
- ADR-0002's key-derivation settings are superseded by ADR-0015; PRD R16's check and R17 are Built; backlog items 1 (Vault) and 13 are done, item 3 records the spec's out-of-date vault table, and item 15 notes the desktop app's missing passphrase confirmation.
- README: removed the note saying release files don't exist yet, now that 1.1.0 is published.

### Fixed
- The desktop window now shows weak categories, as PRD R3 says; the bridge had left them out of its result.
- A keyword at the end of a sentence or bullet kept its full stop (`kubernetes.`), so it never matched the same word elsewhere.
- README banner: removed the space after the first asterisk on the proof-of-concept line, which stopped the italics. The wording is unchanged.

### Security
- The desktop window rendered dossier text, mission-template names and keywords, and error messages as raw HTML, and had no Content-Security-Policy, so a template with HTML in a category name could run script in the window; export bundle names weren't checked, so `../x` wrote outside `bundles/`. Now every value is shown as text (no `innerHTML` in `app.js`), `index.html` sets a strict CSP (`default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'`; `'unsafe-eval'` is in `script-src` only because pywebview builds its bridge functions with `new Function`), and one shared check (`resolve_bundle_path`) limits bundle names to 1-64 letters, digits, `.`, `-`, `_` and keeps the output inside `bundles/`, for both the desktop app and `qv export`. ([ADR-0029](docs/decisions/0029-desktop-text-only-csp-bundle-names.md))
- Upgraded pyasn1 0.6.4 → 0.6.5 (a dependency of google-auth, used by the Gemini provider) to fix CVE-2026-119194, CVE-2026-119195, CVE-2026-119196 and CVE-2026-119197.
- Upgraded opentelemetry-api 1.45.1 → 1.45.2 (a dependency of the anthropic SDK) to fix CVE-2026-126360. Lockfile change only.

## [1.1.0] - 2026-10-28

The first version published as release files: a pre-release on [GitHub Releases](https://github.com/dustenatx/QuestVector/releases). Installing it needs Python 3.14 (see Removed).

### Added
- `Release` GitHub Actions workflow (`.github/workflows/release.yml`), run only when a `v*` tag is pushed: it tests the tagged commit, checks it is on `main` and that the tag matches `__version__`, builds the wheel and sdist, writes `SHA256SUMS`, attests build provenance with `actions/attest` v4.2.2, and publishes a pre-release with this changelog section as its notes. The release is created as a draft and published only as the last step. ([ADR-0014](docs/decisions/0014-github-releases.md))
- `.github/rulesets/tags.json`: a tag ruleset under which only the repository admin can create, move, or delete `v*` tags (applied by the owner after merge).
- `tests/test_workflows.py`: every workflow pins its actions to a commit SHA with a version comment and checks out without persisting credentials; `release.yml` keeps its tag-only trigger, its permissions, and its draft-then-publish order.
- README "Install from a release" and "Upgrade" instructions, with checksum and attestation checks; `docs/DEVELOPMENT.md` release steps for the owner.
- Opt-in live test of narrative generation against a local Ollama server (`tests/test_ollama_live.py`, on when `QV_OLLAMA_LIVE=1`), with a synthetic dossier, job description, and answer key in `tests/fixtures/ollama_live/`, fixture checks that always run, and a how-to in `docs/DEVELOPMENT.md`.
- `qv vault set-key --timeout SECONDS`: how long to wait for a local Ollama response (default 300 seconds, up from a fixed 120).
- `Security` GitHub Actions workflow: gitleaks (git history), Semgrep (static analysis), and pip-audit (dependency vulnerabilities) on every pull request and push to `main`; gitleaks and Semgrep results also go to the Security tab. ([ADR-0011](docs/decisions/0011-github-security-baseline.md))
- `.github/dependabot.yml`: weekly version updates for pip and GitHub Actions, with a 7-day cooldown.
- `SECURITY.md`: how to report a vulnerability privately.
- `.github/rulesets/main.json`: the `main` branch ruleset (squash-only pull requests, required checks, no bypass), kept in the repo so changes are reviewed, and matching the live ruleset field for field, including the defaults GitHub fills in; and a `CLAUDE.md` rule that a CI job can't be renamed without updating it in the same pull request.
- `Tests` GitHub Actions workflow: pytest with coverage on Python 3.12 and 3.13, a run without the AI extras, and mypy plus pyflakes, on every pull request and push to `main`.
- 90% line-coverage floor in `pyproject.toml` (measured 95%).
- `CLAUDE.md` with project rules for AI-assisted development.
- `.gitignore` for Python caches, build output, virtual environments, and OS files.
- `templates/boilerplate.qv-mission.yaml` in the current schema, at the path
  `CONTRIBUTING_TEMPLATES.md` already referenced.
- `templates/community/README.md` explaining where contributed templates go.
- README "Documentation" section pointing to `docs/QuestVector_Spec.pdf` and
  the video overview.
- `docs/BACKLOG.md` with planned work from the 15 Oct 2026 review.
- This changelog and the decisions log in `docs/decisions/`.
- `docs/PRD.md`, the first product requirements document (draft 0.1).
- `docs/DEVELOPMENT.md`: developer setup, checks, conventions, and the release steps.
- README "Fill in your dossier first" section explaining the dossier format, and a documentation index.
- mypy, pyflakes, and the type stubs mypy needs (`types-PyYAML`, `types-reportlab`) in the dev tools (now the `dev` dependency group), so the spec's "mypy clean" claim can be reproduced.

### Changed
- Distribution: ADR-0001 is narrowed by [ADR-0014](docs/decisions/0014-github-releases.md) so CI may publish release files to GitHub Releases; the app still makes no new network calls, and there is no PyPI package, hosting, or telemetry. The README distribution policy and the PRD non-goal say the same, and the PRD's definition of done now applies to the first full (non-pre-release) release instead of 1.1.0.
- The build backend is pinned to `setuptools==84.2.1` (was `>=68.0`), so release builds don't pick up the newest setuptools of the day; the license metadata uses the SPDX form (`license = "MIT"`, `license-files`) that setuptools now requires.
- `CLAUDE.md`: the CI-job rule covers jobs that run on pull requests (tag-only release jobs aren't required checks), and only the owner creates release tags.
- Python 3.14 only (`requires-python >=3.14`, `.python-version`), with uv for contributors and a committed `uv.lock` covering every platform, extra, and group. The lock only takes releases at least 7 days old (`exclude-newer`), matching Dependabot's cooldown. Users can still install with plain pip on Python 3.14. ([ADR-0013](docs/decisions/0013-python-3-14-uv-lock.md))
- CI moved to uv: `astral-sh/setup-uv` v10.3.0 (pinned to a commit SHA, uv 0.13.1) and `uv sync --locked` in every job. Tests run on Python 3.14 only, full and minimal; the required checks are now `pytest (full, Python 3.14)` and `pytest (minimal, Python 3.14)` (`.github/rulesets/main.json` updated). The test and template-validation jobs run on `ubuntu-24.04` instead of `ubuntu-latest`.
- pip-audit audits every package in `uv.lock` (all extras and groups, including macOS-only packages) instead of what one pip install resolves, and pip-audit itself is locked in an `audit` dependency group.
- Dependabot updates Python dependencies through its `uv` ecosystem, so its pull requests update `uv.lock`.
- The dev tools moved from the `[dev]` extra to a `dev` dependency group, which `uv sync` installs by default.
- The default Ollama model is now `gemma4:12b-it-q4_K_M` instead of `llama3.1`: in [ADR-0012](docs/decisions/0012-ollama-thinking-off.md)'s comparison it invented facts in 0 of 5 runs against 3 of 5 for llama3.1:8b, and the owner's real-dossier run on 27 Oct 2026 backed the choice. It is an 8 GB download instead of 4.9 GB; anyone relying on the old default should run `ollama pull gemma4:12b-it-q4_K_M` or set `--model llama3.1`.
- Backlog item 9 lists three follow-ups from the PR #7 review: a connection reset mid-response escapes as a raw error, `qv vault set-key` resets the timeout when `--timeout` is omitted, and the desktop prompt omits the template's tone.
- Ollama requests switch thinking off (`"think": false`), so thinking models such as qwen3.5 and gemma4 answer within the 600-token limit instead of spending it all on hidden reasoning. ([ADR-0012](docs/decisions/0012-ollama-thinking-off.md))
- Backlog item 1 now records that negative statements in a dossier ("no hands-on Kubernetes") count as keyword matches, and that role titles in `##` headings may not count toward matching ("manager" reported as a gap under "Engineering Manager" headings).
- Every GitHub Action is pinned to a commit SHA (checkout v7.0.1, setup-python v7.0.0), and checkout no longer keeps the token in the working copy.
- Template validation runs on every pull request, so it can be a required check.
- The Ollama generator rejects a host that isn't an `http://` or `https://` URL, instead of passing it to urllib, which also opens `file://` URLs.
- The 13 tests that patch a cloud AI SDK now skip, with the install command as the reason, when that SDK isn't installed, instead of failing.
- Template-validation workflow rewritten for the Python build: installs with
  pip on Python 3.12 and validates every template under `templates/` with
  `qv template validate`. It previously set up Node and ran `npm install`, so
  it could not install the CLI. ([ADR-0007](docs/decisions/0007-ci-validates-all-templates.md))
- Workflow feedback moved from a canned PR comment to real per-file results
  in the Actions run summary; the workflow token is now read-only and the
  check works on pull requests from forks.
  ([ADR-0008](docs/decisions/0008-ci-results-in-run-summary.md))
- README tagline no longer promises application tracking, which doesn't exist; the status table now says testing used simulated AI providers.
- Contributing guide and issue templates no longer refer to the unbuilt Web Cockpit as usable.
- README clarifies that `MASTER_DEVELOPER_SPEC.pdf`, cited by the code's
  "Spec reference" notes, is the original design spec and is not in the repo.

### Removed
- Support for Python 3.12 and 3.13: 1.1.0 installs only on Python 3.14. Anyone upgrading from 1.0.0 on an older Python needs a new 3.14 virtual environment.
- The `[dev]` extra: `pip install -e ".[dev]"` no longer installs the test tools; contributors use `uv sync` (see `docs/DEVELOPMENT.md`).
- `tj-actions/changed-files` dependency from the workflow.
- Seven stale starter templates in `templates/starter/` and
  `templates/boilerplate.yaml`, which used the pre-reconciliation schema and
  failed validation. The bundled copies in `questvector/data/starter_templates/`
  are the only source. ([ADR-0009](docs/decisions/0009-bundled-starter-templates-only.md))
- Committed `.DS_Store` files.

### Fixed
- A slow Ollama response raised a raw `TimeoutError`, which escaped the desktop app's narrative bridge; it now raises `LLMError` with the time limit and how to raise it.
- A model that isn't downloaded was reported as "Could not reach the local Ollama server -- is it running?"; it now says the model isn't downloaded and to run `ollama pull`. Other HTTP errors from Ollama now include Ollama's own message.
- An empty Ollama answer always asked "has the model been pulled?"; running out of tokens, including on hidden reasoning, now gets its own message.

## [1.0.0] - 2026-09-15

### Added
- Narrative generation through four interchangeable providers: Anthropic,
  OpenAI, Google Gemini, and a local Ollama server, behind one data-driven
  provider registry. ([ADR-0004](docs/decisions/0004-data-driven-llm-provider-registry.md),
  [ADR-0005](docs/decisions/0005-ollama-over-plain-http.md))
- `qv vault set-key` options `--provider`, `--model`, and `--host`, printing each
  provider's key-setup link before prompting.
- Desktop provider picker in the Vault panel.
- `qv --version`.
- Per-provider key storage in the vault, with automatic migration of
  single-key vault files.
- `docs/QuestVector_Spec.pdf`, the system specification for the Python build.
- Video overview, `docs/QuestVector - The AI Capability Ladder.mp4`.
- Tests expanded from 108 to 142, covering every provider, the vault
  migration, and the new CLI flags.

### Changed
- `questvector.__version__` is the single source of truth for the version;
  `pyproject.toml` reads it dynamically. ([ADR-0010](docs/decisions/0010-single-source-version.md))
- Package moved under `questvector/`; CLI installed as the `qv` entry point.
- Documentation updated to the local-only distribution policy, replacing the
  original spec's "Zero-Cloud" framing. ([ADR-0001](docs/decisions/0001-local-only-distribution.md))
- README states the project is untested: narrative generation has not run
  against a live provider.

### Fixed
- LICENSE copyright holder and a "(a)" to "(c)" typo.
- A type error in the PDF exporter (`list[object]` to `list[Flowable]`).

## Pre-release history

### 2026-09-09
- First Python build: `qv` CLI (`launch`, `sync-ast`, `export`,
  `template validate`, `vault set-key`), the matching engine and G-Force
  score, the reconciled mission-template schema, seven bundled starter
  templates, the encrypted local vault, PDF and DOCX export, the pywebview
  desktop app, Anthropic narrative generation, and 108 tests.
  ([ADR-0002](docs/decisions/0002-aes-256-gcm-local-vault.md),
  [ADR-0003](docs/decisions/0003-reconciled-template-schema.md),
  [ADR-0006](docs/decisions/0006-independent-g-force-formula.md))
- README note that the project is pre-beta.

### 2026-09-04
- Repository created with the design-stage configuration: issue templates,
  the template-validation workflow, `CONTRIBUTING_TEMPLATES.md`, the MIT
  license, README, and starter templates. Files moved to the repository root.
- `tj-actions/changed-files` updated to v47 (Dependabot pull request #1 and a
  follow-up commit).

[Unreleased]: https://github.com/BearingQuest/questvector/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/BearingQuest/questvector/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/dustenatx/QuestVector/compare/70f380d...v1.1.0
[1.0.0]: https://github.com/dustenatx/QuestVector/commit/70f380d
