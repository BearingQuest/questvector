"""Weekly check that no default model in questvector/core/llm.py has been retired.

Run by .github/workflows/model-check-weekly.yml (backlog item 18, ADR-0031). It
reads each remote provider's public deprecation page, looks for the default model
ID where the page lists deprecated or shut-down models (never where it lists
replacements), and opens or updates one GitHub issue per problem.

Standard library only, and outside the ``questvector`` package, so it never ships
in the wheel and the job needs no install. It reads the defaults from llm.py with
``ast`` instead of importing it. Page text is untrusted: it is parsed, never
executed, and any of it that reaches an issue passes through :func:`clean`.

Exit codes: 0 all clear; 1 a default was found on a deprecation page, a page could
not be read, or an issue could not be written; 2 the script itself is misconfigured.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
LLM_PATH = ROOT / "questvector" / "core" / "llm.py"
USER_AGENT = "QuestVector-model-check (+https://github.com/BearingQuest/questvector)"
GITHUB_API = "https://api.github.com"
# Issues are matched by title and by this author, so an outsider can't open an
# issue with the same title and keep the real one from being created.
BOT_LOGIN = "github-actions[bot]"
TIMEOUT_SECONDS = 20
ATTEMPTS = 3
MAX_PAGE_BYTES = 3_000_000
MAX_ISSUE_PAGES = 10
EXCERPT_CHARS = 160
# Providers whose default has no deprecation page to read.
EXEMPT = frozenset({"ollama"})

_DEFAULT_NAME = re.compile(r"DEFAULT_([A-Z0-9]+)_MODEL")
_SNAPSHOT_SUFFIX = re.compile(r"\d{8}|\d{4}-\d{2}-\d{2}")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._:-]*")
_UNSAFE_TEXT = re.compile(r"[^A-Za-z0-9 .,:;()/_+'-]")
_PAGE_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November"
    r"|December) \d{1,2}, \d{4}\b"
)


class ScriptError(Exception):
    """The script cannot do its job (bad configuration, or a GitHub call failed)."""


class FetchError(Exception):
    """A page could not be fetched."""


@dataclass(frozen=True)
class Clear:
    """The default is not listed as deprecated or shut down."""


@dataclass(frozen=True)
class Found:
    """The default is listed as deprecated or shut down.

    Attributes:
        state: How the page marks it, already cleaned for an issue body.
        date: The date the page gives, already cleaned.
        excerpt: The matched row, already cleaned and short.
    """

    state: str
    date: str
    excerpt: str


@dataclass(frozen=True)
class Unreadable:
    """The page could not be fetched, or its stable marker was not there."""

    reason: str


Outcome = Clear | Found | Unreadable


@dataclass(frozen=True)
class Source:
    """One provider's deprecation page and the parser for its structure."""

    name: str
    url: str
    parse: Callable[[str, str], Outcome]


class IssueClient(Protocol):
    """The three GitHub issue calls the check needs."""

    def open_issues(self) -> list[dict[str, Any]]: ...

    def create(self, title: str, body: str) -> int: ...

    def update(self, number: int, body: str) -> None: ...


def clean(text: str, limit: int = EXCERPT_CHARS) -> str:
    """Make page text safe to quote in an issue body.

    Keeps letters, digits, spaces and ``.,:;()/_+'-`` only, so no markup, link,
    ``@mention``, ``#`` reference, backtick or pipe survives, then collapses
    whitespace and cuts to ``limit`` characters.
    """
    return " ".join(_UNSAFE_TEXT.sub(" ", text).split())[:limit]


def tokens(cell: str) -> list[str]:
    """Split a table cell into lower-case model IDs and names, whole tokens only."""
    return [token.rstrip(".:-") for token in _TOKEN.findall(cell.lower())]


def same_model(default: str, candidate: str) -> bool:
    """True if ``candidate`` is ``default`` or a dated snapshot of it.

    Pages often list ``claude-sonnet-4-5-20250929`` for the alias
    ``claude-sonnet-4-5``. Anything else after the ID (``-tts``, ``-lite``) is a
    different model.
    """
    default = default.lower()
    candidate = candidate.lower()
    if candidate == default:
        return True
    return candidate.startswith(default + "-") and bool(
        _SNAPSHOT_SUFFIX.fullmatch(candidate[len(default) + 1 :])
    )


def mentions(cell: str, default: str) -> bool:
    """True if any token in ``cell`` is the default model or a snapshot of it."""
    return any(same_model(default, token) for token in tokens(cell))


def excerpt(cells: list[str]) -> str:
    """A short plain-text rendering of a matched table row."""
    return clean("; ".join(clean(cell, 60) for cell in cells[:5]))


def read_defaults(path: Path) -> dict[str, str]:
    """Read the ``DEFAULT_<PROVIDER>_MODEL`` string constants from llm.py.

    Uses ``ast`` so llm.py is never imported or run.

    Args:
        path: The source file to read.

    Returns:
        A map of lower-case provider ID to default model ID.

    Raises:
        ScriptError: If a matching constant is not a plain string literal.
    """
    defaults: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        match = _DEFAULT_NAME.fullmatch(target.id)
        if not match:
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            raise ScriptError(f"{target.id} in {path.name} is not a plain string literal")
        defaults[match.group(1).lower()] = value.value
    return defaults


class _Tables(HTMLParser):
    """Collects every table's cell text, and the text of each ``<h1>``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._skip = 0
        self._h1: list[str] | None = None
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def _end_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _end_row(self) -> None:
        self._end_cell()
        if self._row is not None and self._table is not None:
            self._table.append(self._row)
        self._row = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "h1":
            self._h1 = []
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._end_row()
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._end_cell()
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "h1" and self._h1 is not None:
            self.h1.append(" ".join("".join(self._h1).split()))
            self._h1 = None
        elif tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr":
            self._end_row()
        elif tag == "table" and self._table is not None:
            self._end_row()
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._h1 is not None:
            self._h1.append(data)
        if self._cell is not None:
            self._cell.append(data)


def _read_tables(page: str) -> _Tables:
    parser = _Tables()
    parser.feed(page)
    parser.close()
    return parser


def _column(header: list[str], name: str) -> int | None:
    """Index of the first header cell that starts with ``name`` (case-insensitive)."""
    for index, cell in enumerate(header):
        if cell.lower().startswith(name):
            return index
    return None


def _cell(row: list[str], index: int | None) -> str:
    return row[index] if index is not None and index < len(row) else ""


def parse_anthropic(page: str, default: str) -> Outcome:
    """Read the "Model status" table of platform.claude.com's deprecations page.

    Marker: an ``<h1>`` naming model deprecations and a table headed ``API model
    name`` and ``Current state``. The default is deprecated or retired when its
    row's state is anything but ``Active``. The per-announcement tables, which
    hold the recommended replacements, are never read.
    """
    parsed = _read_tables(page)
    status = [
        table
        for table in parsed.tables
        if table
        and _column(table[0], "api model name") is not None
        and _column(table[0], "current state") is not None
    ]
    if not any("model deprecations" in h1.lower() for h1 in parsed.h1) or not status:
        return Unreadable("the 'Model deprecations' heading or the 'Model status' table is missing")
    rows = 0
    for table in status:
        header = table[0]
        name, state = _column(header, "api model name"), _column(header, "current state")
        retires = _column(header, "tentative retirement date")
        for row in table[1:]:
            rows += 1
            if mentions(_cell(row, name), default) and _cell(row, state).lower() != "active":
                return Found(
                    state=clean(_cell(row, state)) or "not Active",
                    date=clean(_cell(row, retires)) or "no date on the page",
                    excerpt=excerpt(row),
                )
    return Clear() if rows else Unreadable("the 'Model status' table has no rows")


def parse_openai(page: str, default: str) -> Outcome:
    """Read the model tables of developers.openai.com's deprecations page.

    Marker: an ``<h1>`` naming deprecations and at least one table with an
    ``Affected model`` column. The default is deprecated when it is named in that
    column of the upcoming or the past table. The replacement columns are never
    read, and feature and endpoint tables have no such column.
    """
    parsed = _read_tables(page)
    models = [
        table
        for table in parsed.tables
        if table and _column(table[0], "affected model") is not None
    ]
    if not any("deprecations" in h1.lower() for h1 in parsed.h1) or not models:
        return Unreadable("the 'Deprecations' heading or an 'Affected model' table is missing")
    rows = 0
    for table in models:
        header = table[0]
        affected = _column(header, "affected model")
        shutdown, status = _column(header, "shutdown date"), _column(header, "status")
        for row in table[1:]:
            rows += 1
            if mentions(_cell(row, affected), default):
                return Found(
                    state=clean(_cell(row, status)) or "listed under past deprecations",
                    date=clean(_cell(row, shutdown)) or "no date on the page",
                    excerpt=excerpt(row),
                )
    return Clear() if rows else Unreadable("the deprecation tables have no rows")


_NOSCRIPT = re.compile(r"<noscript><pre>(.*?)</pre></noscript>", re.DOTALL)
_GEMINI_H1 = re.compile(r"(?m)^# Gemini deprecations[ \t]*$")
_GEMINI_BLOCK = re.compile(r"(?m)^#{1,6} ([^\n]+)$|\{% table %\}\n((?s:.*?))\{% /table %\}")
_GEMINI_HEADER = ["model", "release date", "shutdown date", "recommended replacement"]


def parse_gemini(page: str, default: str) -> Outcome:
    """Read the Markdown that aistudio.google.com embeds in a ``<noscript>`` block.

    The page's visible DOM is built by JavaScript (no tables in the raw HTML), but
    the server also embeds the page's Markdown source. Marker: a ``# Gemini
    deprecations`` line and a table headed ``Model, Release date, Shutdown date,
    Recommended replacement``. The default is deprecated when it is in the Model
    column of a row that has a shutdown date, a recommended replacement, or sits
    under a "Deprecated" heading. If Google drops or reshapes that block, the
    marker fails and the check reports "can't read", never "all clear".
    """
    text = next(
        (
            html.unescape(block)
            for block in _NOSCRIPT.findall(page)
            if _GEMINI_H1.search(html.unescape(block))
        ),
        "",
    )
    if not text:
        return Unreadable("the embedded '# Gemini deprecations' Markdown is missing")
    heading, rows, found_table = "", 0, False
    for match in _GEMINI_BLOCK.finditer(text):
        if match.group(1) is not None:
            heading = match.group(1)
            continue
        chunks = re.split(r"(?m)^[ \t]*---[ \t]*$", match.group(2))
        parsed = [re.findall(r"(?m)^[ \t]*\*(?: ([^\n]*))?[ \t]*$", chunk) for chunk in chunks]
        header = [cell.strip().lower() for cell in parsed[0][:4]]
        if header != _GEMINI_HEADER:
            continue
        found_table = True
        for cells in (row for row in parsed[1:] if row):
            rows += 1
            cells = [cell.strip() for cell in cells]
            if not mentions(cells[0], default):
                continue
            shutdown, replacement = _cell(cells, 2), _cell(cells, 3)
            reasons = []
            if _PAGE_DATE.search(shutdown):
                reasons.append("has a shutdown date")
            if replacement:
                reasons.append("has a recommended replacement")
            if "deprecated" in heading.lower():
                reasons.append("is under a Deprecated heading")
            if reasons:
                return Found(
                    state=clean(", ".join(reasons)),
                    date=clean(shutdown) or "no date on the page",
                    excerpt=excerpt(cells),
                )
    if not found_table:
        return Unreadable("the Model, Release date, Shutdown date table is missing")
    return Clear() if rows else Unreadable("the deprecation tables have no rows")


SOURCES: dict[str, Source] = {
    "anthropic": Source(
        "Anthropic",
        "https://platform.claude.com/docs/en/about-claude/model-deprecations",
        parse_anthropic,
    ),
    "openai": Source(
        "OpenAI",
        "https://developers.openai.com/api/docs/deprecations",
        parse_openai,
    ),
    "gemini": Source(
        "Gemini",
        "https://aistudio.google.com/docs/deprecations",
        parse_gemini,
    ),
}


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to https on the host that was asked for."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if new.scheme != "https" or new.hostname != old.hostname:
            raise urllib.error.HTTPError(
                newurl, code, "redirect away from the page's https host", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str, *, sleep: Callable[[float], None] = time.sleep) -> str:
    """Fetch a page over HTTPS, retrying a transient failure.

    Args:
        url: An ``https://`` URL.
        sleep: Called between attempts; tests pass a no-op.

    Returns:
        The body decoded as UTF-8.

    Raises:
        FetchError: For a non-HTTPS URL, a 4xx answer, an oversized page, or a
            failure that persisted through every attempt.
    """
    if urllib.parse.urlsplit(url).scheme != "https":
        raise FetchError("not an https URL")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    opener = urllib.request.build_opener(_SameHostRedirect)
    last = "no attempt was made"
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(5.0 * attempt)
        try:
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                body: bytes = response.read(MAX_PAGE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code < 500:
                raise FetchError(last) from exc
            continue
        except OSError as exc:  # URLError and TimeoutError are OSErrors
            last = type(exc).__name__
            continue
        if len(body) > MAX_PAGE_BYTES:
            raise FetchError("page is larger than 3 MB")
        return body.decode("utf-8", errors="replace")
    raise FetchError(f"{last} after {ATTEMPTS} attempts")


class GitHubIssues:
    """The GitHub REST issue calls, with the run's own token (HTTPS only)."""

    def __init__(self, repo: str, token: str) -> None:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise ScriptError("GITHUB_REPOSITORY is not in the form owner/name")
        self._base = f"{GITHUB_API}/repos/{repo}/issues"
        self._token = token

    def _call(self, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            code = exc.code if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
            raise ScriptError(f"GitHub {method} {url.rsplit('/', 1)[-1]} failed: {code}") from exc

    def open_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for page in range(1, MAX_ISSUE_PAGES + 1):
            batch = self._call("GET", f"{self._base}?state=open&per_page=100&page={page}")
            issues.extend(batch)
            if len(batch) < 100:
                break
        return issues

    def create(self, title: str, body: str) -> int:
        created = self._call("POST", self._base, {"title": title, "body": body})
        return int(created["number"])

    def update(self, number: int, body: str) -> None:
        self._call("PATCH", f"{self._base}/{number}", {"body": body})


def upsert_issue(client: IssueClient, title: str, body: str) -> str:
    """Update the open issue with this exact title, or open one.

    Only an open issue written by the Actions bot counts, and pull requests,
    which GitHub lists with issues, are skipped. The body is replaced; no comment
    is added.

    Returns:
        A short description of what was done, for the log.
    """
    for issue in client.open_issues():
        if (
            issue.get("title") == title
            and issue.get("state", "open") == "open"
            and "pull_request" not in issue
            and (issue.get("user") or {}).get("login") == BOT_LOGIN
        ):
            client.update(int(issue["number"]), body)
            return f"updated issue #{issue['number']}"
    return f"opened issue #{client.create(title, body)}"


def found_issue(
    name: str, model: str, url: str, found: Found, checked: str, run: str
) -> tuple[str, str]:
    """Title and body of the issue for a default listed as deprecated or shut down."""
    title = f"Default model deprecated or retired: {name} {model}"
    body = (
        f"The {name} default `{model}` in `questvector/core/llm.py` is listed on the "
        f"provider's deprecation page.\n\n"
        f"- State: {found.state}\n"
        f"- Date on the page: {found.date}\n"
        f"- Page text: {found.excerpt}\n"
        f"- Source: {url}\n\n"
        f"Last checked: {checked} (UTC) by {run}.\n\n"
        "Choose the replacement the page recommends, update the default (see "
        '"Default models for remote providers" in docs/DEVELOPMENT.md), and close '
        "this issue. The weekly check never closes issues."
    )
    return title, body


def unreadable_issue(name: str, url: str, why: str, checked: str, run: str) -> tuple[str, str]:
    """Title and body of the issue for a page the check could not read."""
    title = f"Model check can't read the {name} deprecation page"
    body = (
        f"The weekly check could not tell whether the {name} default model is retired.\n\n"
        f"- Page: {url}\n"
        f"- Why: {clean(why)}\n\n"
        f"Last checked: {checked} (UTC) by {run}.\n\n"
        "The page may have been redesigned or may be down. Look at it, fix the "
        "parser in scripts/check_default_models.py if the layout changed, and close "
        "this issue. The weekly check never closes issues."
    )
    return title, body


def run_checks(
    defaults_path: Path,
    *,
    fetch: Callable[[str], str],
    client: IssueClient | None,
    today: str,
    run_url: str,
    write: Callable[[str], None],
) -> tuple[int, list[tuple[str, str, str]]]:
    """Check every default against its provider's page and write the issues.

    Args:
        defaults_path: The llm.py to read the defaults from.
        fetch: Returns a page's text for a URL; raises :class:`FetchError`.
        client: Where issues go, or ``None`` for a dry run (nothing is written).
        today: The date for "Last checked", as ``YYYY-MM-DD``.
        run_url: A link to this run, or a plain phrase when there is none.
        write: Receives each log line.

    Returns:
        The exit code (0 clear, 1 a problem), and ``(provider, model, result)``
        rows for the run summary.

    Raises:
        ScriptError: If a default has no mapped page and isn't exempt.
    """
    defaults = read_defaults(defaults_path)
    unmapped = sorted(set(defaults) - set(SOURCES) - EXEMPT)
    if unmapped:
        raise ScriptError(f"no deprecation page is mapped for: {', '.join(unmapped)}")
    exit_code = 0
    rows: list[tuple[str, str, str]] = []
    for provider in sorted(defaults):
        model = defaults[provider]
        if provider in EXEMPT:
            write(f"{provider}: skipped, no deprecation page for a local model")
            rows.append((provider, model, "skipped (no deprecation page)"))
            continue
        source = SOURCES[provider]
        try:
            outcome = source.parse(fetch(source.url), model)
        except FetchError as exc:
            outcome = Unreadable(f"fetching the page failed: {clean(str(exc))}")
        if isinstance(outcome, Clear):
            write(f"{provider}: {model} is not listed as deprecated")
            rows.append((provider, model, "clear"))
            continue
        exit_code = 1
        if isinstance(outcome, Found):
            title, body = found_issue(source.name, model, source.url, outcome, today, run_url)
            result = f"FOUND: {outcome.state}, {outcome.date}"
        else:
            title, body = unreadable_issue(source.name, source.url, outcome.reason, today, run_url)
            result = f"CAN'T READ: {outcome.reason}"
        write(f"{provider}: {model}: {result}")
        rows.append((provider, model, result))
        if client is None:
            write(f"  dry run, would open or update: {title}")
            continue
        try:
            write(f"  {upsert_issue(client, title, body)}: {title}")
        except ScriptError as exc:
            write(f"  could not write the issue: {exc}")
    return exit_code, rows


def _summary(rows: list[tuple[str, str, str]]) -> str:
    lines = ["| Provider | Default | Result |", "|---|---|---|"]
    lines += [f"| {provider} | `{model}` | {clean(result)} |" for provider, model, result in rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; see the module docstring for the exit codes."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--dry-run", action="store_true", help="print what would happen; needs no token"
    )
    args = parser.parse_args(argv)

    def write(line: str) -> None:
        sys.stdout.write(line + "\n")

    env = os.environ
    client: IssueClient | None = None
    try:
        if not args.dry_run:
            token = env.get("GITHUB_TOKEN", "")
            if not token:
                raise ScriptError("GITHUB_TOKEN is not set (use --dry-run to run without it)")
            client = GitHubIssues(env.get("GITHUB_REPOSITORY", ""), token)
        run_id = env.get("GITHUB_RUN_ID", "")
        server, repo = env.get("GITHUB_SERVER_URL", ""), env.get("GITHUB_REPOSITORY", "")
        run_url = (
            f"{server}/{repo}/actions/runs/{run_id}"
            if server and repo and run_id
            else "a local run"
        )
        today = datetime.datetime.now(datetime.UTC).date().isoformat()
        code, rows = run_checks(
            LLM_PATH, fetch=fetch_page, client=client, today=today, run_url=run_url, write=write
        )
    except ScriptError as exc:
        sys.stderr.write(f"check_default_models: {exc}\n")
        return 2
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(_summary(rows))
    return code


if __name__ == "__main__":
    sys.exit(main())
