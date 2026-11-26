"""Tests for scripts/check_default_models.py, the weekly retired-model check (R29).

No network and no token: the pages are small synthetic fixtures that copy each
provider page's structure (headers, table layout, where replacements sit) with
made-up model IDs, and GitHub is a fake client.
"""

from __future__ import annotations

import ast
import html
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_default_models.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("check_default_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_default_models"] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module


cdm = _load()

DEFAULT = "model-x-2"


# --- fixtures that copy each page's structure ------------------------------------------


def _table(header: list[str], rows: list[list[str]]) -> str:
    def tr(cells: list[str], tag: str) -> str:
        return "<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>"

    return "<table>" + tr(header, "th") + "".join(tr(row, "td") for row in rows) + "</table>"


ANTHROPIC_STATUS = ["API model name", "Current state", "Deprecated", "Tentative retirement date"]
ANTHROPIC_ANNOUNCED = ["Retirement date", "Deprecated model", "Recommended replacement"]


def anthropic_page(
    status: list[list[str]],
    announced: list[list[str]] | None = None,
    *,
    h1: str = "Model deprecations",
    header: list[str] = ANTHROPIC_STATUS,
) -> str:
    heading = f"<h1>{h1}</h1>" if h1 else ""
    return (
        f"<html><body>{heading}<h2>Model status</h2>{_table(header, status)}"
        f"<h2>Announcements</h2>{_table(ANTHROPIC_ANNOUNCED, announced or [])}</body></html>"
    )


OPENAI_UPCOMING = [
    "Shutdown date",
    "Affected model",
    "Status",
    "Recommended replacement",
    "Notice date",
]
OPENAI_FEATURES = [
    "Shutdown date",
    "Affected feature or endpoint",
    "Status",
    "Recommended replacement",
    "Notice date",
]
OPENAI_PAST = ["Shutdown date", "Affected model or feature", "Listed replacement", "Notice date"]


def openai_page(
    upcoming: list[list[str]],
    past: list[list[str]] | None = None,
    features: list[list[str]] | None = None,
    *,
    h1: str = "Deprecations",
    upcoming_header: list[str] = OPENAI_UPCOMING,
) -> str:
    heading = f"<h1>{h1}</h1>" if h1 else ""
    return (
        f"<html><body>{heading}{_table(upcoming_header, upcoming)}"
        f"{_table(OPENAI_FEATURES, features or [])}{_table(OPENAI_PAST, past or [])}"
        "</body></html>"
    )


def gemini_table(rows: list[tuple[str, str, str, str]], first: str = "Model") -> str:
    text = f"{{% table %}}\n  * {first}\n  * Release date\n  * Shutdown date\n"
    text += "  * Recommended replacement\n"
    for model, release, shutdown, replacement in rows:
        text += f"\n  ---\n\n  * `{model}`\n  * {release}\n  * {shutdown}\n  * {replacement}\n"
    return text + "{% /table %}\n"


def gemini_page(markdown: str, *, h1: bool = True) -> str:
    source = ("# Gemini deprecations\n\nIntro.\n\n" if h1 else "") + markdown
    # The real page is an app shell whose Markdown sits HTML-escaped in a noscript block.
    return (
        "<!doctype html><html><body><app-root></app-root>"
        f"<noscript><pre>{html.escape(source)}</pre></noscript></body></html>"
    )


NO_DATE = "No shutdown date announced"


# --- Anthropic ----------------------------------------------------------------------


def test_anthropic_default_marked_deprecated_is_found() -> None:
    """R29: a default whose state isn't Active is found, with the retirement date."""
    page = anthropic_page([[DEFAULT, "Deprecated", "Sep 30, 2026", "Nov 30, 2026"]])
    found = cdm.parse_anthropic(page, DEFAULT)
    assert isinstance(found, cdm.Found)
    assert (found.state, found.date) == ("Deprecated", "Nov 30, 2026")
    assert DEFAULT in found.excerpt


def test_anthropic_dated_snapshot_of_an_alias_default_is_found() -> None:
    """R29: the page lists the dated ID of an alias default, and that still counts."""
    page = anthropic_page([[f"{DEFAULT}-20260101", "Retired", "Jan 1, 2026", "Feb 1, 2026"]])
    assert isinstance(cdm.parse_anthropic(page, DEFAULT), cdm.Found)


def test_anthropic_active_default_is_clear() -> None:
    """R29: an Active row is not a deprecation."""
    page = anthropic_page([[DEFAULT, "Active", "N/A", "Not sooner than Sep 1, 2027"]])
    assert isinstance(cdm.parse_anthropic(page, DEFAULT), cdm.Clear)


def test_anthropic_default_listed_only_as_a_replacement_is_clear() -> None:
    """R29: a replacement is not a deprecation signal, whether or not the status lists it."""
    announced = [["Dec 1, 2026", "old-model-1-20250101", DEFAULT]]
    other = [["old-model-1-20250101", "Deprecated", "Sep 1, 2026", "Dec 1, 2026"]]
    assert isinstance(cdm.parse_anthropic(anthropic_page(other, announced), DEFAULT), cdm.Clear)
    active = [[DEFAULT, "Active", "N/A", "Not sooner than Sep 1, 2027"], *other]
    assert isinstance(cdm.parse_anthropic(anthropic_page(active, announced), DEFAULT), cdm.Clear)


def test_anthropic_look_alike_id_is_not_the_default() -> None:
    """R29: `model-x-2-tts` is another model, not a snapshot of `model-x-2`."""
    page = anthropic_page([[f"{DEFAULT}-tts", "Deprecated", "Sep 1, 2026", "Dec 1, 2026"]])
    assert isinstance(cdm.parse_anthropic(page, DEFAULT), cdm.Clear)


@pytest.mark.parametrize(
    "page",
    [
        anthropic_page([[DEFAULT, "Deprecated", "a", "b"]], h1=""),
        anthropic_page([[DEFAULT, "Deprecated", "a", "b"]], header=["Model", "Status", "x", "y"]),
        anthropic_page([]),
        "<html><body><div id='root'></div></body></html>",
    ],
    ids=["no-heading", "renamed-columns", "no-rows", "javascript-shell"],
)
def test_anthropic_missing_marker_is_unreadable_not_clear(page: str) -> None:
    """R29: a redesigned page is reported as can't read, never as all clear."""
    assert isinstance(cdm.parse_anthropic(page, DEFAULT), cdm.Unreadable)


# --- OpenAI -------------------------------------------------------------------------


def test_openai_default_named_among_affected_models_is_found() -> None:
    """R29: the default inside a display name with a snapshot ID is found, with its date."""
    row = ["Jan 14, 2027", f"Model X ({DEFAULT}-2025-01-01)", "Deprecated", "model-y-3", "Oct 1"]
    found = cdm.parse_openai(openai_page([row]), DEFAULT)
    assert isinstance(found, cdm.Found)
    assert (found.state, found.date) == ("Deprecated", "Jan 14, 2027")


def test_openai_default_in_past_deprecations_is_found() -> None:
    """R29: the past table has no status column; being listed there means shut down."""
    past = [["Oct 23, 2026", f"other-1, {DEFAULT}, {DEFAULT}-completions", "model-y-3", "Apr 1"]]
    found = cdm.parse_openai(
        openai_page([["Jan 1, 2027", "a", "Deprecated", "b", "c"]], past), DEFAULT
    )
    assert isinstance(found, cdm.Found)
    assert found.state == "listed under past deprecations"
    assert found.date == "Oct 23, 2026"


def test_openai_default_listed_only_as_a_replacement_is_clear() -> None:
    """R29: the replacement columns, and the feature table, are never read."""
    upcoming = [["Jan 14, 2027", "old-1", "Deprecated", f"{DEFAULT} or model-z-1", "Oct 1"]]
    past = [["Oct 23, 2026", "old-2", DEFAULT, "Apr 1"]]
    features = [["Nov 30, 2026", f"endpoint using {DEFAULT}", "Deprecated", DEFAULT, "Jun 3"]]
    assert isinstance(cdm.parse_openai(openai_page(upcoming, past, features), DEFAULT), cdm.Clear)


def test_openai_look_alike_id_is_not_the_default() -> None:
    """R29: `model-x-2-tts` and `model-x-2-mini` are other models; matching is by whole token."""
    rows = [
        ["Jan 6, 2027", f"{DEFAULT}-tts, {DEFAULT}-tts-2025-03-20", "Deprecated", "n", "Oct 1"],
        ["Jan 6, 2027", f"{DEFAULT}-mini", "Deprecated", "n", "Oct 1"],
    ]
    assert isinstance(cdm.parse_openai(openai_page(rows), DEFAULT), cdm.Clear)


@pytest.mark.parametrize(
    "page",
    [
        openai_page([["Jan 1, 2027", DEFAULT, "Deprecated", "x", "y"]], h1=""),
        "<html><body><h1>Deprecations</h1>"
        + _table(OPENAI_FEATURES, [["Nov 30, 2026", DEFAULT, "Deprecated", "x", "y"]])
        + "</body></html>",
        "<html><body><h1>Deprecations</h1></body></html>",
        "<html><body><h1>Deprecations</h1>" + _table(OPENAI_UPCOMING, []) + "</body></html>",
    ],
    ids=["no-heading", "no-model-table", "no-tables", "no-rows"],
)
def test_openai_missing_marker_is_unreadable_not_clear(page: str) -> None:
    """R29: no heading, no 'Affected model' table, or no rows means can't read."""
    assert isinstance(cdm.parse_openai(page, DEFAULT), cdm.Unreadable)


# --- Gemini -------------------------------------------------------------------------


def test_gemini_default_under_a_deprecated_heading_is_found() -> None:
    """R29: the Markdown in the noscript block is read; a Deprecated section row is found."""
    table = gemini_table([(DEFAULT, "Feb 5, 2025", "June 1, 2026", "model-y-3")])
    found = cdm.parse_gemini(
        gemini_page(f"## X models\n\n### Deprecated models\n\n{table}"), DEFAULT
    )
    assert isinstance(found, cdm.Found)
    assert found.date == "June 1, 2026"
    assert "Deprecated heading" in found.state


def test_gemini_default_with_a_shutdown_date_in_a_main_table_is_found() -> None:
    """R29: a real shutdown date marks a deprecation even outside a Deprecated section."""
    table = gemini_table([(DEFAULT, "May 7, 2026", "May 7, 2027", "model-y-3")])
    found = cdm.parse_gemini(gemini_page(f"## X models\n\n{table}"), DEFAULT)
    assert isinstance(found, cdm.Found)
    assert "shutdown date" in found.state


def test_gemini_default_with_no_shutdown_date_and_no_replacement_is_clear() -> None:
    """R29: a current model, with 'No shutdown date announced' and no replacement, is clear."""
    table = gemini_table([(DEFAULT, "Jul 21, 2026", NO_DATE, "")])
    assert isinstance(cdm.parse_gemini(gemini_page(f"## X models\n\n{table}"), DEFAULT), cdm.Clear)


def test_gemini_default_listed_only_as_a_replacement_is_clear() -> None:
    """R29: the replacement column of another model's row is not a deprecation."""
    table = gemini_table(
        [
            ("old-model-1", "Feb 5, 2025", "June 1, 2026", f"`{DEFAULT}`"),
            ("old-model-2", "Feb 5, 2025", "N/A", f"`{DEFAULT}` (routes there)"),
        ]
    )
    page = gemini_page(f"## X models\n\n### Deprecated models\n\n{table}")
    assert isinstance(cdm.parse_gemini(page, DEFAULT), cdm.Clear)


@pytest.mark.parametrize(
    "page",
    [
        "<html><body><app-root></app-root></body></html>",
        gemini_page(f"## X\n\n{gemini_table([(DEFAULT, 'a', NO_DATE, '')])}", h1=False),
        gemini_page(f"## X\n\n{gemini_table([(DEFAULT, 'a', NO_DATE, '')], first='Agent')}"),
        gemini_page("## X\n\nNo tables here.\n"),
        gemini_page(f"## X\n\n{gemini_table([])}"),
    ],
    ids=["no-noscript", "no-heading", "wrong-header", "no-table", "no-rows"],
)
def test_gemini_missing_marker_is_unreadable_not_clear(page: str) -> None:
    """R29: if Google drops or reshapes the embedded Markdown, the check can't read it."""
    assert isinstance(cdm.parse_gemini(page, DEFAULT), cdm.Unreadable)


# --- untrusted page text ------------------------------------------------------------


def test_page_text_is_reduced_to_plain_short_text_before_it_reaches_an_issue() -> None:
    """R29: no markup, link, mention, reference, backtick or pipe survives, and length is capped."""
    hostile = "<img src=x onerror=1> [a](http://e.example) @everyone #12 `x` | **b** " + "z" * 5000
    cleaned = cdm.clean(hostile)
    assert len(cleaned) <= cdm.EXCERPT_CHARS
    assert not set(cleaned) & set('<>[]@#`|*!=\\"{}')
    page = anthropic_page([[f"{DEFAULT} @everyone <b>", f"Deprecated {hostile}", "x", hostile]])
    found = cdm.parse_anthropic(page, DEFAULT)
    assert isinstance(found, cdm.Found)
    for text in (found.state, found.date, found.excerpt):
        assert len(text) <= cdm.EXCERPT_CHARS
        assert not set(text) & set('<>[]@#`|*!=\\"{}')


# --- fetching -----------------------------------------------------------------------


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


class FakeOpener:
    def __init__(self, *outcomes: bytes | BaseException) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x.example/", code, "msg", {}, None)  # type: ignore[arg-type]


def _use(monkeypatch: pytest.MonkeyPatch, opener: FakeOpener) -> None:
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: opener)


def test_fetch_sends_a_descriptive_user_agent_with_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R29: the fetch is identified, bounded in time, and decodes the body."""
    opener = FakeOpener("café".encode())
    _use(monkeypatch, opener)
    assert cdm.fetch_page("https://x.example/p") == "café"
    request, timeout = opener.calls[0]
    assert request.get_header("User-agent") == cdm.USER_AGENT
    assert "QuestVector" in cdm.USER_AGENT and timeout == cdm.TIMEOUT_SECONDS


def test_fetch_refuses_a_non_https_url_without_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """R29: HTTPS only."""
    opener = FakeOpener()
    _use(monkeypatch, opener)
    for url in ("http://x.example/", "file:///etc/passwd", "ftp://x.example/"):
        with pytest.raises(cdm.FetchError):
            cdm.fetch_page(url)
    assert opener.calls == []


def test_fetch_does_not_retry_a_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """R29: a 404 is final; the error reaches the issue as 'HTTP 404'."""
    opener = FakeOpener(_http_error(404))
    _use(monkeypatch, opener)
    with pytest.raises(cdm.FetchError, match="HTTP 404"):
        cdm.fetch_page("https://x.example/", sleep=lambda _s: None)
    assert len(opener.calls) == 1


def test_fetch_retries_a_transient_failure_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """R29: one 503 or timeout doesn't open an issue; three in a row do."""
    sleeps: list[float] = []
    opener = FakeOpener(_http_error(503), TimeoutError(), b"ok")
    _use(monkeypatch, opener)
    assert cdm.fetch_page("https://x.example/", sleep=sleeps.append) == "ok"
    assert len(sleeps) == 2
    opener = FakeOpener(_http_error(503), urllib.error.URLError("down"), _http_error(502))
    _use(monkeypatch, opener)
    with pytest.raises(cdm.FetchError, match="after 3 attempts"):
        cdm.fetch_page("https://x.example/", sleep=lambda _s: None)


def test_fetch_refuses_an_oversized_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """R29: the page body is capped."""
    _use(monkeypatch, FakeOpener(b"x" * (cdm.MAX_PAGE_BYTES + 1)))
    with pytest.raises(cdm.FetchError, match="larger"):
        cdm.fetch_page("https://x.example/")


def test_redirects_are_followed_only_to_https_on_the_same_host() -> None:
    """R29: a redirect to http or to another host is refused."""
    handler = cdm._SameHostRedirect()
    request = urllib.request.Request("https://x.example/a")
    for target in ("http://x.example/b", "https://evil.example/b"):
        with pytest.raises(urllib.error.HTTPError):
            handler.redirect_request(request, None, 302, "Found", {}, target)
    followed = handler.redirect_request(request, None, 302, "Found", {}, "https://x.example/b")
    assert followed is not None and followed.full_url == "https://x.example/b"


# --- issue create versus update -----------------------------------------------------


def _issue(number: int, title: str, login: str = cdm.BOT_LOGIN, **extra: Any) -> dict[str, Any]:
    return {"number": number, "title": title, "state": "open", "user": {"login": login}, **extra}


class FakeClient:
    """Stands in for GitHub; has no comment call, so a test can't pass by commenting."""

    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []
        self.created: list[tuple[str, str]] = []
        self.updated: list[tuple[int, str]] = []
        self.fail_on_write = False

    def open_issues(self) -> list[dict[str, Any]]:
        return self.issues

    def create(self, title: str, body: str) -> int:
        if self.fail_on_write:
            raise cdm.ScriptError("GitHub POST issues failed: 403")
        self.created.append((title, body))
        return 100 + len(self.created)

    def update(self, number: int, body: str) -> None:
        self.updated.append((number, body))


def test_issue_is_created_when_none_is_open() -> None:
    """R29: no open issue with the title means one is created."""
    client = FakeClient([_issue(1, "Another problem")])
    assert cdm.upsert_issue(client, "T", "B") == "opened issue #101"
    assert client.created == [("T", "B")] and client.updated == []


def test_issue_is_updated_not_duplicated_when_one_is_open() -> None:
    """R29: the same title from the Actions bot gets a new body, and nothing new is created."""
    client = FakeClient([_issue(7, "T")])
    assert cdm.upsert_issue(client, "T", "new body") == "updated issue #7"
    assert client.updated == [(7, "new body")] and client.created == []


@pytest.mark.parametrize(
    "lookalike",
    [
        _issue(7, "T", login="someone-else"),
        {**_issue(7, "T"), "state": "closed"},
        _issue(7, "T", pull_request={"url": "x"}),
        _issue(7, "T extra"),
    ],
    ids=["other-author", "closed", "pull-request", "other-title"],
)
def test_issue_lookalikes_do_not_count_as_the_open_issue(lookalike: dict[str, Any]) -> None:
    """R29: an outsider's issue with the same title can't suppress the real one."""
    client = FakeClient([lookalike])
    assert cdm.upsert_issue(client, "T", "B").startswith("opened issue")
    assert client.updated == []


class FakeUrlopen:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.calls.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return FakeResponse(json.dumps(response).encode())


def test_github_client_calls_the_issue_api_with_the_run_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R29: list, create and update go to the repo's issues over HTTPS with a Bearer token."""
    fake = FakeUrlopen([_issue(1, "a")] * 100, [_issue(2, "b")], {"number": 9}, {})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    client = cdm.GitHubIssues("owner/name", "TOKEN-VALUE")
    assert [issue["number"] for issue in client.open_issues()][-1] == 2
    assert client.create("T", "B") == 9
    client.update(9, "B2")
    urls = [call.full_url for call in fake.calls]
    assert all(url.startswith("https://api.github.com/repos/owner/name/issues") for url in urls)
    assert [call.get_method() for call in fake.calls] == ["GET", "GET", "POST", "PATCH"]
    assert fake.calls[0].get_header("Authorization") == "Bearer TOKEN-VALUE"


def test_github_client_errors_are_script_errors_without_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R29: an API failure becomes a ScriptError that doesn't repeat the token."""
    monkeypatch.setattr(urllib.request, "urlopen", FakeUrlopen(_http_error(403)))
    client = cdm.GitHubIssues("owner/name", "TOKEN-VALUE")
    with pytest.raises(cdm.ScriptError, match="403") as caught:
        client.create("T", "B")
    assert "TOKEN-VALUE" not in str(caught.value)
    with pytest.raises(cdm.ScriptError):
        cdm.GitHubIssues("not a repo", "t")


# --- the whole run ------------------------------------------------------------------

LLM_TEXT = """\
DEFAULT_ANTHROPIC_MODEL = "model-x-2"
DEFAULT_OPENAI_MODEL = "model-o-2"
DEFAULT_GEMINI_MODEL = "model-g-2"
DEFAULT_OLLAMA_MODEL = "local:1b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_TIMEOUT = 300.0
DEFAULT_MODEL = DEFAULT_ANTHROPIC_MODEL
"""


def clear_pages() -> dict[str, str]:
    return {
        cdm.SOURCES["anthropic"].url: anthropic_page(
            [["other-1", "Active", "N/A", "Not sooner than 2027"]],
            [["Dec 1, 2026", "old-1", "model-x-2"]],
        ),
        cdm.SOURCES["openai"].url: openai_page(
            [["Jan 14, 2027", "old-1", "Deprecated", "model-o-2", "Oct 1"]]
        ),
        cdm.SOURCES["gemini"].url: gemini_page(
            f"## X\n\n{gemini_table([('old-1', 'a', 'June 1, 2026', '`model-g-2`')])}"
        ),
    }


def run(
    tmp_path: Path,
    pages: dict[str, Any],
    client: FakeClient | None,
    llm_text: str = LLM_TEXT,
) -> tuple[int, list[tuple[str, str, str]], list[str]]:
    llm = tmp_path / "llm.py"
    llm.write_text(llm_text, encoding="utf-8")
    lines: list[str] = []

    def fetch(url: str) -> str:
        page = pages[url]
        if isinstance(page, Exception):
            raise page
        return str(page)

    code, rows = cdm.run_checks(
        llm,
        fetch=fetch,
        client=client,
        today="2026-12-07",
        run_url="https://github.com/o/r/actions/runs/1",
        write=lines.append,
    )
    return code, rows, lines


def test_all_clear_exits_zero_opens_nothing_and_skips_ollama_by_name(tmp_path: Path) -> None:
    """R29: nothing is deprecated, so exit 0 and no issue; Ollama has no page and is skipped."""
    client = FakeClient()
    code, rows, lines = run(tmp_path, clear_pages(), client)
    assert code == 0 and client.created == [] and client.updated == []
    assert [row[2] for row in rows if row[0] != "ollama"] == ["clear"] * 3
    assert any(line.startswith("ollama: skipped") for line in lines)


def test_a_found_default_opens_one_issue_with_model_date_and_source(tmp_path: Path) -> None:
    """R29: found means an issue naming the model, the page's date and the source link; exit 1."""
    pages = clear_pages()
    pages[cdm.SOURCES["openai"].url] = openai_page(
        [["Jan 14, 2027", "Model O (model-o-2-2025-01-01)", "Deprecated", "model-p-3", "Oct 1"]]
    )
    client = FakeClient()
    code, _rows, _lines = run(tmp_path, pages, client)
    assert code == 1 and client.updated == []
    [(title, body)] = client.created
    assert title == "Default model deprecated or retired: OpenAI model-o-2"
    assert "Jan 14, 2027" in body and cdm.SOURCES["openai"].url in body
    assert "Last checked: 2026-12-07 (UTC)" in body and "actions/runs/1" in body


def test_the_next_run_updates_the_open_issue_instead_of_adding_another(tmp_path: Path) -> None:
    """R29: a second run with the problem still there rewrites the body, with the new date."""
    pages = clear_pages()
    pages[cdm.SOURCES["gemini"].url] = gemini_page(
        f"## X\n\n### Deprecated models\n\n{gemini_table([('model-g-2', 'a', 'June 1, 2026', '')])}"
    )
    first = FakeClient()
    run(tmp_path, pages, first)
    [(title, _body)] = first.created
    second = FakeClient([_issue(5, title)])
    code, _rows, _lines = run(tmp_path, pages, second)
    assert code == 1 and second.created == []
    assert [number for number, _ in second.updated] == [5]


def test_a_fetch_error_opens_a_separate_cant_read_issue(tmp_path: Path) -> None:
    """R29: a page that can't be fetched is its own issue, with the reason; exit 1."""
    pages: dict[str, Any] = clear_pages()
    pages[cdm.SOURCES["anthropic"].url] = cdm.FetchError("HTTP 503 after 3 attempts")
    client = FakeClient()
    code, _rows, _lines = run(tmp_path, pages, client)
    assert code == 1
    [(title, body)] = client.created
    assert title == "Model check can't read the Anthropic deprecation page"
    assert "HTTP 503" in body and cdm.SOURCES["anthropic"].url in body


def test_a_missing_marker_opens_a_cant_read_issue_not_an_all_clear(tmp_path: Path) -> None:
    """R29: a redesigned page is reported, never passed quietly."""
    pages = clear_pages()
    pages[cdm.SOURCES["gemini"].url] = "<html><app-root></app-root></html>"
    client = FakeClient()
    code, _rows, _lines = run(tmp_path, pages, client)
    assert code == 1
    assert client.created[0][0] == "Model check can't read the Gemini deprecation page"


def test_an_issue_write_failure_still_fails_the_run_and_checks_the_rest(tmp_path: Path) -> None:
    """R29: if GitHub refuses an issue, the run is red and the other providers still run."""
    pages = clear_pages()
    pages[cdm.SOURCES["anthropic"].url] = cdm.FetchError("HTTP 500")
    pages[cdm.SOURCES["openai"].url] = cdm.FetchError("HTTP 500")
    client = FakeClient()
    client.fail_on_write = True
    code, rows, lines = run(tmp_path, pages, client)
    assert code == 1 and len(rows) == 4
    assert sum("could not write the issue" in line for line in lines) == 2


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    """R29: with no client, problems are reported as what would be done."""
    pages = clear_pages()
    pages[cdm.SOURCES["openai"].url] = cdm.FetchError("HTTP 500")
    code, _rows, lines = run(tmp_path, pages, None)
    assert code == 1 and any("dry run, would open or update" in line for line in lines)


# --- reading the defaults -----------------------------------------------------------


def test_defaults_are_read_from_llm_py_without_importing_it() -> None:
    """R29: the three remote defaults and Ollama's are read with ast."""
    defaults = cdm.read_defaults(cdm.LLM_PATH)
    assert set(defaults) == {"anthropic", "openai", "gemini", "ollama"}
    assert all(isinstance(model, str) and model for model in defaults.values())


def test_only_default_model_string_constants_are_read(tmp_path: Path) -> None:
    """R29: the alias, the host and the timeout don't match DEFAULT_<PROVIDER>_MODEL."""
    path = tmp_path / "llm.py"
    path.write_text(LLM_TEXT, encoding="utf-8")
    assert cdm.read_defaults(path) == {
        "anthropic": "model-x-2",
        "openai": "model-o-2",
        "gemini": "model-g-2",
        "ollama": "local:1b",
    }


def test_a_default_that_is_not_a_string_literal_is_an_error(tmp_path: Path) -> None:
    """R29: a computed default is refused, never silently skipped."""
    path = tmp_path / "llm.py"
    path.write_text('DEFAULT_NEWCO_MODEL = "a" + "b"\n', encoding="utf-8")
    with pytest.raises(cdm.ScriptError, match="DEFAULT_NEWCO_MODEL"):
        cdm.read_defaults(path)


def test_every_default_in_llm_py_has_a_page_mapped_or_is_ollama() -> None:
    """R29: a new DEFAULT_*_MODEL constant with no mapped page fails here (Ollama excepted)."""
    unmapped = set(cdm.read_defaults(cdm.LLM_PATH)) - set(cdm.SOURCES) - cdm.EXEMPT
    assert not unmapped, f"add a deprecation page for {sorted(unmapped)} in scripts/"
    assert {"ollama"} == cdm.EXEMPT


def test_a_new_default_with_no_page_stops_the_run_before_any_fetch(tmp_path: Path) -> None:
    """R29: the run refuses to pass quietly when a default has no page mapped."""
    with pytest.raises(cdm.ScriptError, match="newco"):
        run(tmp_path, {}, FakeClient(), LLM_TEXT + 'DEFAULT_NEWCO_MODEL = "n-1"\n')


def test_the_page_urls_are_exactly_the_ones_in_development_md() -> None:
    """R29: the three source pages are the ones DEVELOPMENT.md names for the defaults."""
    text = (ROOT / "docs" / "DEVELOPMENT.md").read_text(encoding="utf-8")
    for source in cdm.SOURCES.values():
        assert source.url.startswith("https://")
        assert f"]({source.url})" in text, source.url


def test_the_script_uses_only_the_standard_library_and_lives_outside_the_package() -> None:
    """R29: nothing to install in CI, and nothing added to the wheel."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imported <= set(sys.stdlib_module_names)
    assert "questvector" not in imported
    assert SCRIPT.parent == ROOT / "scripts"


# --- command line -------------------------------------------------------------------


def test_main_without_a_token_exits_two_unless_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R29: a missing token is a configuration error, not a silent pass."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(cdm, "fetch_page", lambda url: pytest.fail("fetched"))
    assert cdm.main([]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_main_dry_run_reads_the_real_defaults_and_writes_the_run_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R29: end to end on the real llm.py with fake pages; the step summary is a table."""
    defaults = cdm.read_defaults(cdm.LLM_PATH)
    pages = {
        cdm.SOURCES["anthropic"].url: anthropic_page([["other-1", "Active", "N/A", "2027"]]),
        cdm.SOURCES["openai"].url: openai_page([["Jan 1, 2027", "old-1", "Deprecated", "n", "o"]]),
        cdm.SOURCES["gemini"].url: gemini_page(
            f"## X\n\n{gemini_table([('old-1', 'a', 'June 1, 2026', '')])}"
        ),
    }
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(cdm, "fetch_page", lambda url: pages[url])
    assert cdm.main(["--dry-run"]) == 0
    assert "anthropic: " + defaults["anthropic"] in capsys.readouterr().out
    table = summary.read_text(encoding="utf-8")
    assert table.startswith("| Provider | Default | Result |")
    assert f"`{defaults['gemini']}`" in table
