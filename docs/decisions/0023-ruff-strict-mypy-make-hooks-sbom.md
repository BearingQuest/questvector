# 0023. Ruff, strict mypy, make targets, a pre-push hook and a release SBOM

- **Status:** Accepted; amends [0011](0011-github-security-baseline.md) (the
  `mypy and pyflakes` required check is now `ruff and mypy`) and
  [0014](0014-github-releases.md) (the release carries an SBOM)
- **Date:** 2026-11-15

## Context
Phase 2 of the baseline work (PR C) copies the tooling of
`BearingQuest/project-template` (its decision rows of 11 and 14 Nov 2026):
REPO-02 (mypy), REPO-03 (ruff), REPO-08 (one place tests start a process),
CI-12 (SBOM) and the hooks item of the Phase 1 audit. The formatting pass
landed first on its own as pull request #43 (`f19c691`), because `main` only
accepts squash merges: a reformat commit inside this pull request would never
reach `main`, so it could not be listed in `.git-blame-ignore-revs`.

## Decision
- **ruff replaces pyflakes.** `ruff==0.17.4` (the template's pin) in the `dev`
  group, `pyflakes` removed from the group, CI and the release workflow. Rules
  `E F W I B UP S SIM RUF T20`, line length 100, Python 3.14, `tests/**` may
  `assert` (S101). `spikes/` is excluded: it is a finished spike kept for the
  record, not maintained code (see `docs/spikes/2026-10-browser-pyodide.md`).
- **The required check is renamed `ruff and mypy`** (job `static-checks` in
  `tests.yml`): `ruff check .`, `ruff format --check .`, then `mypy`.
  `.github/rulesets/main.json` and `REQUIRED_CHECKS` in
  `tests/test_workflows.py` change with it. The old name never reports on this
  pull request, so the owner applies `main.json` from the branch before
  merging, as `docs/DEVELOPMENT.md` describes.
- **mypy is strict for the whole `questvector` package** (`strict = true`,
  `files = ["questvector"]`, no overrides), where the template is strict on its
  package and `scripts/`. Four errors were fixed to get there: the Gemini and
  Ollama generators now check that the provider's text is a `str` and raise
  `LLMError` otherwise (a behaviour change, with tests per provider), `main()`
  in `cli.py` types its handler as `Callable[[argparse.Namespace], int]`, and
  `_load_template_by_id` in the desktop bridge has a return type.
- **S310 (`urlopen` accepts any scheme) is guarded, not suppressed blindly.**
  `OllamaNarrativeGenerator.__init__` already rejects any host that isn't an
  `http://` or `https://` URL with a host. The tests now cover http, https,
  `file://`, `ftp://`, and a missing scheme or host, and that no URL is opened
  after a rejection. The two flagged lines carry `# noqa: S310` pointing at
  that guard. No new validation code.
- **Other lint decisions.** `questvector/cli.py` and `tests/live_narrative.py`
  may print (T201 per-file ignores; their job is terminal output), a departure
  from the template's block. `AlertLevel(str, Enum)` keeps its base classes
  (`# noqa: UP042`, because `StrEnum` changes `str()`); the en dash in the
  workspace stub text stays (`# noqa: RUF001`, it is written into user files);
  the fake passphrases in two tests carry `# noqa: S105`; a duplicate
  stopword pair was removed; a `try/except/pass` became
  `contextlib.suppress`.
- **Make targets** `help check audit sbom hooks`. `make check` is ruff check,
  ruff format --check, mypy, pytest. `make audit` runs exactly the export and
  pip-audit commands of the `pip-audit` job in `security.yml` (all extras and
  groups, platform markers stripped, `--only-group audit`), not the template's
  plain export, which this lock cannot use; `tests/test_hooks.py` fails if the
  two differ.
- **`.githooks/pre-push`** scans the pushed commits with gitleaks;
  `make hooks` turns it on once per clone. `tests/test_hooks.py` runs it
  against a fake gitleaks.
- **`tests/_proc.py`** is the one place tests start a process, with the one
  reasoned `noqa: S603`; a test fails if another test file calls `subprocess`
  or `os.system`. No existing test started a process, so nothing moved.
- **SBOM (CI-12).** `make sbom` writes `dist/sbom.cdx.json`: CycloneDX 1.5 of
  the locked runtime dependencies and the AI extras (`--all-extras --no-dev`,
  because the wheel can install the extras), via uv's preview
  `sbom-export`. The release `build` job runs it before `SHA256SUMS` (which now
  covers it); the `release` job attests it and attaches it to the draft, and
  still runs no repository code. `tests/test_sbom.py` fails if a package from
  the `dev` or `audit` group appears. If a uv release changes the preview
  export, the fallback is `cyclonedx-py` on the exported requirements, added
  only with the owner's approval.
- **`.git-blame-ignore-revs`** lists the formatting commit of #43; the file
  and `docs/DEVELOPMENT.md` say how to use it.

## Consequences
- Departures from the template: `T201` ignores for two files; strict mypy
  covers the whole package, not `scripts/` (there is none); `make audit`
  follows `security.yml`; the SBOM includes the extras; the template's e2e
  target has no counterpart here, because the project has no end-to-end test
  suite yet.
- `CLAUDE.md` still tells agents to run `pyflakes` before every commit until
  PR D updates it.
- Other open pull requests wait on the new `ruff and mypy` check until rebased.
- Releases get a fourth file, `sbom.cdx.json`, so the check in
  `docs/DEVELOPMENT.md` expects four files.
- A Gemini or Ollama reply whose text isn't a string now fails with a clear
  error instead of an `AttributeError`.
- The new guards were mutation-checked by hand on 15 Nov 2026, in a scratch
  copy, one change at a time: 46 mutations (the ruff and mypy settings, each
  Makefile recipe, the hook's range, exit status, bash 3.2 syntax, missing
  gitleaks message and executable bit, `.gitignore` and blame-file entries,
  `_proc.py`'s `noqa`, a bare `subprocess` call in a test, the required check
  name, the workflow steps for ruff, the SBOM, its checksums, attestation and
  release attachment, and the Ollama and Gemini checks). One survived: letting
  the Ollama guard accept `file://`, because the only `file://` host in the
  tests had no host part. A `file://localhost/...` case now catches it.
