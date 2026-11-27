# 0031. Weekly check for retired default models, in CI only

- **Status:** Accepted
- **Date:** 2026-11-26

## Context
A provider can deprecate or shut down a default model with little notice. When
checked on 4 Nov 2026 the Gemini default had been shut down since 1 Jun 2026,
and the Anthropic default was due to retire within the month. Backlog item 8's
planned run-time warning tells a user after the fact; the owner wants to hear
first. Backlog item 18 (decided 4 Nov 2026) asks for a weekly GitHub Actions
check. The daily half of item 18 is `pip-audit-daily.yml`
([0022](0022-scheduled-audit-scorecard-and-claude-review.md)).

I read the three saved deprecation pages (raw HTML, fetched with curl, 26 Nov
2026) before designing the parsers. Two options came up for page text that is
awkward to read: skip that provider, or read the most stable part of the page
and fail loudly when it is gone. The second was chosen.

## Decision
- **`model-check-weekly.yml`**: Mondays 08:17 UTC and `workflow_dispatch`,
  never on pull requests, so it is not a required check and
  `.github/rulesets/main.json` does not change
  ([0011](0011-github-security-baseline.md)). `ubuntu-24.04`, a 10-minute
  timeout, a concurrency group, `persist-credentials: false`, every action
  pinned to a commit SHA. Workflow token `contents: read`; the one job adds
  `issues: write`. No secret other than the run's own token, no API key.
  Python 3.14 comes from `setup-uv` (cache off, the same pin as the daily
  audit) and `uv run --no-project --python 3.14`, because the repo's code and
  ruff target 3.14.
- **`scripts/check_default_models.py`**: standard library only and outside the
  `questvector` package, so it never ships in the wheel and installs nothing.
  It reads the `DEFAULT_<PROVIDER>_MODEL` string constants from
  `questvector/core/llm.py` with `ast`, without importing it. A computed
  default is an error. A default with no page mapped fails the run and a test;
  Ollama is skipped by name, because a local model has no deprecation page.
  `mypy` checks the script too (`files` in `pyproject.toml`).
- **What is read, per provider.** The URLs are exactly those in
  `docs/DEVELOPMENT.md`. Each parser looks only at the columns that list
  deprecated models, never at the replacement columns, because the defaults
  themselves appear on these pages as replacements.
  - *Anthropic* (tables are in the raw HTML): the "Model status" table. The
    default is found when its row's state is anything but `Active`. Marker: an
    `<h1>` naming model deprecations plus the `API model name` and `Current
    state` headers.
  - *OpenAI* (tables are in the raw HTML): the `Affected model` column of the
    upcoming table (any status) and the past table (listed there means shut
    down). Marker: an `<h1>` naming deprecations plus an `Affected model`
    header. Cells hold several IDs and display names, so matching is by whole
    token.
  - *Gemini* (the visible page is built by JavaScript; the raw HTML has no
    tables): the page's Markdown source, which the server embeds in a
    `<noscript><pre>` block. The default is found when it is in the `Model`
    column of a row that has a shutdown date, a recommended replacement, or
    sits under a "Deprecated" heading. Marker: the `# Gemini deprecations`
    line plus the `Model, Release date, Shutdown date, Recommended replacement`
    header.
  - *Matching.* A page ID matches the default when it is equal, or is the
    default plus a date suffix (`-YYYYMMDD` or `-YYYY-MM-DD`), because
    Anthropic lists `claude-sonnet-4-5-20250929` for the alias
    `claude-sonnet-4-5`. `x-tts` or `x-mini` is a different model.
- **How it decides.** Fetch (HTTPS only, 20 s timeout, a User-Agent naming the
  project, redirects only to https on the same host, 3 MB cap, three attempts
  so one 503 opens nothing), check the marker, then look for the default. Three
  outcomes: found, clear, or can't read. A missing marker, an empty table, a
  fetch error, or an unknown structure is "can't read", never "clear".
- **Issues.** One open issue per problem, found by exact title **and** the
  `github-actions[bot]` author, because anyone can open an issue on a public
  repository and a same-title issue would otherwise stop the real one being
  created. Found: `Default model deprecated or retired: <provider> <model>`,
  with the state, the date the page gives, a short excerpt and the source link.
  Can't read: `Model check can't read the <provider> deprecation page`, with
  the reason. A repeat run replaces the body (with "Last checked: date (UTC)"
  and the run link) and adds no comment. The check never closes an issue; the
  owner does. If a closed problem persists, the next run opens a new issue,
  which is the reminder.
- **The run fails** (exit 1) when anything was found or couldn't be read, or an
  issue couldn't be written, after every provider has been checked. A red run
  sends GitHub's failure email, the one alert that still arrives if the issue
  call fails or issue notifications are muted, and it repeats weekly until the
  problem is fixed. Updating an issue body sends nothing. Exit 2 is a
  misconfigured script. `--dry-run` prints what would happen and needs no token.
- **Page text is untrusted.** The script parses it and never executes it. It
  never reaches a shell or a `${{ }}` expression; the script calls the GitHub
  REST API itself with `GITHUB_TOKEN`. Anything quoted in an issue is cut to
  letters, digits, spaces and `.,:;()/_+'-`, whitespace collapsed, at most 160
  characters, so no markup, link, `@mention`, `#` reference or backtick
  survives. The Gemini page opens with text addressed to AI agents; the parser
  reads table cells only.
- **ADR-0001.** The app makes no new network call. This is CI only, as backlog
  item 18 says; CI already uses the network (setup-uv, pip-audit, Scorecard).
- **Semgrep suppression (one).** Semgrep could not run in the build sandbox
  (its rules come from semgrep.dev), so the first scan was the `semgrep` job on
  PR #57. It flagged
  `python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected`
  on the `urllib.request.urlopen(request, ...)` call in `GitHubIssues._call` in
  `scripts/check_default_models.py` (line 501 when flagged; the call now sits
  in the helper `_send_to_github`, which `_call` alone uses, so the comment fits
  the line limit). The owner approved a `nosemgrep` on that one call on 26 Nov
  2026, the same form as the Ollama call in `questvector/core/llm.py`
  ([0011](0011-github-security-baseline.md)).
  Reason: the rule fears a URL that urllib opens as `file://` or another scheme.
  Here `_call` raises `ScriptError` for any URL that doesn't start with
  `self._base`, the `https://api.github.com/repos/<owner>/<name>/issues` URL
  built in `__init__`, before the request is built, and `update()` refuses an
  issue number that isn't an `int`, so a caller can't steer the path. Enforced
  by `test_github_client_refuses_a_url_outside_the_issues_base_before_any_request`
  and `test_github_client_update_refuses_a_non_int_issue_number`. The page fetch
  in `fetch_page` uses an opener, not `urlopen`, and was not flagged; it
  accepts only https and follows redirects only to https on the same host.

## Consequences
- The owner hears about a deprecated default weeks before a user hits it, and
  about a page the check can no longer read, in the same place.
- **Known limits.** A page redesign breaks a parser; that shows up as a "can't
  read" issue and a red run, not a false all-clear. The Gemini page is built by
  JavaScript, and only its embedded Markdown fallback is read; if Google removes
  or reshapes it, Gemini will be "can't read" until the parser changes. It is
  unverified whether Google serves that block to every User-Agent; the first
  `workflow_dispatch` run is the proof. A provider that renames or silently
  reroutes a model without listing it is not caught, and neither is an alias
  whose snapshot is listed but whose alias is not (the date-suffix rule is the
  mitigation). A state value the Anthropic parser has not seen is treated as
  deprecated, so the owner looks.
- GitHub disables scheduled workflows in a public repository after 60 days with
  no repository activity; re-enable this one from the Actions tab.
- Adding a provider means adding a page and a parser in
  `scripts/check_default_models.py`; a test fails until that is done.
- Item 8's run-time warning is still wanted; the two do different jobs.
