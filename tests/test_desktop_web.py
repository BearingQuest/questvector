"""The desktop window's page: strict CSP, no inline code, and data rendered as text.

R18: the window renders dossier, template and error text as text, under a
strict Content-Security-Policy (ADR-0029).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parents[1] / "questvector" / "desktop" / "web"

EXPECTED_CSP = {
    "default-src": "'none'",
    "script-src": "'self' 'unsafe-eval'",
    "style-src": "'self'",
    "img-src": "'self'",
    "font-src": "'self'",
    "connect-src": "'none'",
    "base-uri": "'none'",
    "form-action": "'none'",
}

BANNED_JS = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]


class _PageScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csp_values: list[str] = []
        self.inline_script = False
        self.style_tags = 0
        self.style_attrs = 0
        self.event_handlers: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta" and (values.get("http-equiv") or "").lower() == (
            "content-security-policy"
        ):
            self.csp_values.append(values.get("content") or "")
        if tag == "script":
            self._in_script = True
            if "src" not in values:
                self.inline_script = True
        if tag == "style":
            self.style_tags += 1
        for name, _ in attrs:
            if name == "style":
                self.style_attrs += 1
            if name.startswith("on"):
                self.event_handlers.append(name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.inline_script = True


def _scan_index() -> _PageScan:
    scan = _PageScan()
    scan.feed((WEB_DIR / "index.html").read_text(encoding="utf-8"))
    return scan


def test_index_has_exactly_the_agreed_csp() -> None:
    scan = _scan_index()
    assert len(scan.csp_values) == 1
    directives = [d.strip() for d in scan.csp_values[0].split(";") if d.strip()]
    parsed = dict(d.split(None, 1) for d in directives)
    assert len(directives) == len(parsed)
    assert parsed == EXPECTED_CSP


def test_index_has_no_inline_code_or_handlers() -> None:
    scan = _scan_index()
    assert not scan.inline_script
    assert scan.style_tags == 0
    assert scan.style_attrs == 0
    assert scan.event_handlers == []


@pytest.mark.parametrize("api", BANNED_JS)
def test_app_js_never_inserts_markup(api: str) -> None:
    """A text scan: a guardrail against reintroducing markup sinks, not proof of safety."""
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert re.search(re.escape(api), source) is None


def test_scan_result_has_places_for_counts_warnings_and_weak_categories() -> None:
    """R3: the window has the count line, weak categories and the negation list, filled as text."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    for element_id in ("gauge-counts", "weak-categories-list", "negation-list"):
        assert f'id="{element_id}"' in html
        assert f'"{element_id}"' in source
    for key in ("counts_text", "weak_categories", "negation_warnings"):
        assert key in source


def test_narrative_result_has_places_for_removed_text_and_flags() -> None:
    """R14: the window lists what the output check removed and flagged, filled as text."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    for element_id in ("narrative-removed", "narrative-flags"):
        assert f'id="{element_id}"' in html
        assert f'"{element_id}"' in source
    assert "response.data" in source and "flag.sentence" in source


def test_export_panel_has_a_style_choice_a_cutoff_box_and_a_notes_list() -> None:
    """R9: the export panel offers the resume style and cutoff, and lists what was left out."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    for element_id in ("export-style", "export-cutoff", "export-notes"):
        assert f'id="{element_id}"' in html
        assert f'"{element_id}"' in source
    assert 'value="resume"' in html
    assert "api.export_bundle(" in source and "style, cutoffYears" in source


def test_export_shows_the_file_check_lines_and_failure_as_text() -> None:
    """R10: the window lists the file check's lines and says when the check failed."""
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "check.lines" in source
    assert "FILE CHECK FAILED" in source
