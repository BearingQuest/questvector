"""Check an exported resume DOCX (PRD R10, ADR-0032).

The file is read two independent ways, with no system tools and no new dependency:

* **A**, through python-docx (paragraphs and tables);
* **B**, through the raw ``word/document.xml`` in the zip, with regular expressions (no
  XML parser, so nothing to expand or fetch).

A finding is ``FAIL`` (the check fails and ``qv`` exits non-zero) or ``WARN`` (reported,
exit code unchanged). Limits, stated plainly: a DOCX is not rendered here, so there is no
page count (python-docx writes none; ``docProps/app.xml`` holds a stale template value);
the check looks for the features R9 forbids and for text problems, and cannot prove a
particular screening system reads the file.
"""

from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import docx

from questvector.core.contact import Contact
from questvector.core.resume import YEAR_RE, cutoff_date
from questvector.exceptions import ExportError

#: Largest uncompressed size accepted for any part of the DOCX (10 MB). A part whose
#: declared size is over it is refused before it is read, and no more than this is read.
MAX_PART_BYTES = 10 * 1024 * 1024

#: Generic filler phrases a resume reads better without (a warning, not a failure).
CLICHE_PHRASES: tuple[str, ...] = (
    "results-driven",
    "team player",
    "detail-oriented",
    "self-starter",
    "go-getter",
    "think outside the box",
    "proven track record",
    "passionate about",
    "hit the ground running",
    "wear many hats",
    "fast-paced environment",
    "strong work ethic",
    "excellent communication skills",
    "thought leader",
    "move the needle",
)

_SECTION_HEADINGS = frozenset(
    {"Summary", "Core Capabilities", "Experience", "Earlier Career", "Selected Results"}
)
# RUF001: the en dash is the date range separator the resume uses (R9).
_RANGE = r"[A-Z][a-z]{2} \d{4} [–-] (?:[A-Z][a-z]{2} \d{4}|Present)"  # noqa: RUF001
_HEADER_RE = re.compile(rf"^(?P<employer>.+) \| {_RANGE}$")
_RANGE_RE = re.compile(_RANGE)
_PRONOUN_RE = re.compile(r"\b(?:he|his|him|himself|she|her|hers|herself)\b", re.IGNORECASE)
_CLICHE_RES = tuple(
    (
        phrase,
        re.compile(
            r"\b" + r"[\s-]+".join(map(re.escape, re.split(r"[\s-]+", phrase))) + r"\b", re.I
        ),
    )
    for phrase in CLICHE_PHRASES
)
_PARAGRAPH_RE = re.compile(r"<w:p(?:\s[^>]*)?(?:/>|>.*?</w:p>)", re.DOTALL)
_TEXT_TOKEN_RE = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>|<w:tab\s*/>|<w:br\s*/>")
_LINE_SNIPPET = 100


@dataclass(frozen=True, slots=True)
class Finding:
    """One problem or warning found in the file.

    Attributes:
        severity: ``"FAIL"`` or ``"WARN"``.
        code: A short name such as ``"table"`` or ``"pronoun"``.
        message: A plain-text description naming the line or field involved.
    """

    severity: str
    code: str
    message: str

    def line(self) -> str:
        """Return the one-line text shown for this finding."""
        return f"{self.severity} {self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The result of checking one DOCX.

    Attributes:
        findings: Every finding, failures first.
        words: Word count from python-docx's paragraphs.
        paragraphs: Paragraph count from python-docx.
        roles: Role header count (the same in both extractions when the check passes).
    """

    findings: tuple[Finding, ...] = field(default_factory=tuple)
    words: int = 0
    paragraphs: int = 0
    roles: int = 0

    @property
    def failures(self) -> tuple[Finding, ...]:
        """Return the ``FAIL`` findings."""
        return tuple(f for f in self.findings if f.severity == "FAIL")

    @property
    def passed(self) -> bool:
        """Return whether there are no ``FAIL`` findings (warnings don't count)."""
        return not self.failures

    def lines(self) -> list[str]:
        """Return one line per finding, then the length line and the verdict."""
        warnings = len(self.findings) - len(self.failures)
        verdict = "PASS" if self.passed else "FAIL"
        return [
            *(f.line() for f in self.findings),
            f"Length: {self.words} words in {self.paragraphs} paragraphs, {self.roles} roles. "
            "Page count: not available for a DOCX (it isn't rendered here).",
            f"Check {verdict}: {len(self.failures)} problem(s), {warnings} warning(s)",
        ]

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable form used by ``--json`` and the desktop bridge."""
        return {
            "passed": self.passed,
            "findings": [
                {"severity": f.severity, "code": f.code, "message": f.message}
                for f in self.findings
            ],
            "words": self.words,
            "paragraphs": self.paragraphs,
            "roles": self.roles,
            "lines": self.lines(),
        }


def _snippet(line: str) -> str:
    text = line.strip()
    return text if len(text) <= _LINE_SNIPPET else text[: _LINE_SNIPPET - 3] + "..."


def _read_parts(path: Path) -> tuple[str, dict[str, str]]:
    """Read ``word/document.xml`` and the rels, refusing any part over the size cap.

    Returns:
        ``(document_xml, extras)``: ``extras`` has the document relationships text and
        the text of each header and footer part.

    Raises:
        ExportError: If the file isn't a DOCX zip, lacks ``word/document.xml``, or any part
            declares an uncompressed size over :data:`MAX_PART_BYTES`.
    """
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ExportError(f"{path.name} is not a readable DOCX (zip) file: {exc}") from exc
    with archive:
        for info in archive.infolist():
            if info.file_size > MAX_PART_BYTES:
                raise ExportError(
                    f"{path.name}: part {info.filename} declares {info.file_size} bytes, over "
                    f"the {MAX_PART_BYTES}-byte limit; not read"
                )

        def read(name: str) -> str:
            with archive.open(name) as handle:
                data = handle.read(MAX_PART_BYTES + 1)
            if len(data) > MAX_PART_BYTES:
                raise ExportError(f"{path.name}: part {name} is over {MAX_PART_BYTES} bytes")
            return data.decode("utf-8", "replace")

        names = archive.namelist()
        if "word/document.xml" not in names:
            raise ExportError(f"{path.name} has no word/document.xml: not a DOCX file")
        document = read("word/document.xml")
        extras = {
            name: read(name)
            for name in names
            if name == "word/_rels/document.xml.rels"
            or re.fullmatch(r"word/(?:header|footer)\d*\.xml", name)
        }
    return document, extras


def _raw_lines(document_xml: str) -> list[str]:
    """Extract paragraph text from the raw XML, keeping empty paragraphs as ``""``."""
    lines = []
    for paragraph in _PARAGRAPH_RE.findall(document_xml):
        parts = []
        for match in _TEXT_TOKEN_RE.finditer(paragraph):
            token = match.group(0)
            if token.startswith("<w:t") and not token.startswith("<w:tab"):
                parts.append(html.unescape(match.group(1)))
            elif token.startswith("<w:tab"):
                parts.append("\t")
            else:
                parts.append("\n")
        lines.append("".join(parts))
    return lines


def _header_findings(source: str, lines: list[str]) -> tuple[list[Finding], int]:
    """Check each ``Employer | dates`` line sits directly under a title line."""
    findings: list[Finding] = []
    headers = 0
    for index, line in enumerate(lines):
        if _HEADER_RE.match(line.strip()):
            headers += 1
            previous = lines[index - 1] if index else ""
            stripped = previous.strip()
            if (
                not stripped
                or stripped.startswith("•")
                or stripped in _SECTION_HEADINGS
                or _HEADER_RE.match(stripped)
            ):
                findings.append(
                    Finding(
                        "FAIL",
                        "role-header",
                        f'{source}: "{_snippet(line)}" is not directly after a title line '
                        f'(the line before it is "{_snippet(previous)}")',
                    )
                )
        elif _RANGE_RE.search(line):
            findings.append(
                Finding(
                    "FAIL",
                    "role-header",
                    f'{source}: a date range is not attached to a company: "{_snippet(line)}"',
                )
            )
    return findings, headers


def check_docx(
    path: Path,
    *,
    contact: Contact,
    cutoff_years: int | None = None,
    today: date | None = None,
) -> CheckReport:
    """Check an exported resume DOCX.

    Args:
        path: The ``.docx`` file.
        contact: The contact details the resume should show.
        cutoff_years: The cutoff the export used, if any; then no year before it may
            appear in the body.
        today: The date the cutoff is measured from (required with ``cutoff_years``).

    Returns:
        A :class:`CheckReport`; ``passed`` is false when any finding is a ``FAIL``.

    Raises:
        ExportError: If the file can't be read as a DOCX, a part is over the size cap, or
            ``cutoff_years`` is given without ``today``.
    """
    if cutoff_years is not None and today is None:
        raise ExportError("check_docx needs today when a cutoff is given")
    document_xml, extras = _read_parts(path)
    try:
        document = docx.Document(str(path))
    except Exception as exc:  # python-docx raises several types for a damaged package
        raise ExportError(f"{path.name} could not be opened as a DOCX: {exc}") from exc

    lines_a = [p.text for p in document.paragraphs]
    lines_b = _raw_lines(document_xml)
    findings: list[Finding] = []

    tables_a = len(document.tables)
    tables_b = len(re.findall(r"<w:tbl[ >]", document_xml))
    if tables_a or tables_b:
        findings.append(
            Finding(
                "FAIL",
                "table",
                f"{tables_a} table(s) found by python-docx, {tables_b} in document.xml",
            )
        )
    layout = (
        ("textbox", len(re.findall(r"<w:txbxContent", document_xml)), "text box(es)"),
        ("tab", len(re.findall(r"<w:tab\s*/>", document_xml)), "tab character(s)"),
        (
            "columns",
            len(
                [n for n in re.findall(r'<w:cols\b[^>]*w:num="(\d+)"', document_xml) if int(n) > 1]
            ),
            "multi-column section(s)",
        ),
    )
    for code, count, what in layout:
        if count:
            findings.append(Finding("FAIL", code, f"{count} {what} in document.xml"))
    header_footer = [
        name
        for name, text in extras.items()
        if name != "word/_rels/document.xml.rels" and "<w:t" in text
    ]
    if header_footer or re.search(r"<w:(?:header|footer)Reference", document_xml):
        findings.append(
            Finding("FAIL", "header-footer", "the document has page header or footer content")
        )

    text_a, text_b = "\n".join(lines_a), "\n".join(lines_b)
    for label, value in contact.fields():
        for source, text in (("python-docx", text_a), ("document.xml", text_b)):
            if value not in text:
                findings.append(
                    Finding("FAIL", "contact", f"{label} ({value}) is missing from {source}")
                )
    rels = extras.get("word/_rels/document.xml.rels", "")
    targets = {html.unescape(t) for t in re.findall(r'Target="([^"]*)"', rels)}
    expected = [f"mailto:{contact.email}", *(url for _label, url in contact.links)]
    for target in expected:
        if target not in targets:
            findings.append(Finding("FAIL", "hyperlink", f"no hyperlink to {target}"))

    header_a, roles_a = _header_findings("python-docx", lines_a)
    header_b, roles_b = _header_findings("document.xml", lines_b)
    findings += header_a + header_b
    if roles_a != roles_b:
        findings.append(
            Finding(
                "FAIL",
                "role-count",
                f"python-docx found {roles_a} role header(s) and document.xml found {roles_b}",
            )
        )
    elif roles_a == 0:
        findings.append(Finding("FAIL", "role-count", "no 'Employer | Mon YYYY – Mon YYYY' lines"))  # noqa: RUF001

    body = [
        _without_contact(line, contact)
        for line in dict.fromkeys([*lines_a, *lines_b])
        if line.strip()
    ]
    if cutoff_years is not None and today is not None:
        floor = cutoff_date(today, cutoff_years).year
        for line in body:
            old = sorted({y for y in YEAR_RE.findall(line) if int(y) < floor})
            if old:
                findings.append(
                    Finding(
                        "FAIL",
                        "year",
                        f'{", ".join(old)} is before the {floor} cutoff: "{_snippet(line)}"',
                    )
                )
    for line in body:
        if _PRONOUN_RE.search(line):
            found = sorted({m.group(0).lower() for m in _PRONOUN_RE.finditer(line)})
            findings.append(
                Finding(
                    "FAIL",
                    "pronoun",
                    f'third-person {", ".join(found)} in: "{_snippet(line)}"',
                )
            )
    for phrase, pattern in _CLICHE_RES:
        for line in body:
            if pattern.search(line):
                findings.append(Finding("WARN", "cliche", f'"{phrase}" in: "{_snippet(line)}"'))

    ordered = sorted(findings, key=lambda f: f.severity != "FAIL")
    return CheckReport(
        findings=tuple(ordered),
        words=sum(len(line.split()) for line in lines_a),
        paragraphs=len(lines_a),
        roles=roles_a,
    )


def _without_contact(line: str, contact: Contact) -> str:
    """Blank the contact values in a line, so a phone number or URL isn't read as body text."""
    for _label, value in contact.fields():
        line = line.replace(value, " ")
    return line
