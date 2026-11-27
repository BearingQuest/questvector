# The en dash is part of the resume date range under test.
"""Tests for questvector.core.export_check: the check of an exported resume DOCX (R10).

Synthetic data only (tests/fixtures/resume). "Today" is passed in, never read.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date
from pathlib import Path

import docx
import pytest

from questvector.core import export_check
from questvector.core.contact import Contact, parse_contact
from questvector.core.export_check import CLICHE_PHRASES, check_docx
from questvector.core.exporter import export_resume
from questvector.core.markdown_parser import parse_dossier
from questvector.core.models import ChronologyEntry, Dossier
from questvector.exceptions import ExportError

FIXTURES = Path(__file__).parent / "fixtures" / "resume"
TODAY = date(2026, 11, 27)


@pytest.fixture()
def contact() -> Contact:
    return parse_contact(FIXTURES / "Contact.md")


def export(
    tmp_path: Path,
    contact: Contact,
    *,
    narrative: str | None = None,
    cutoff_years: int | None = None,
    dossier: Dossier | None = None,
    name: str = "resume.docx",
) -> Path:
    path = tmp_path / name
    export_resume(
        dossier or parse_dossier(FIXTURES, require_roles=True),
        contact,
        path,
        fmt="docx",
        narrative=narrative,
        cutoff_years=cutoff_years,
        today=TODAY,
    )
    return path


def rewrite(path: Path, edit: object) -> Path:
    """Copy ``path`` with ``edit(xml) -> xml`` applied to word/document.xml."""
    out = path.with_name("edited-" + path.name)
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = edit(data.decode("utf-8")).encode("utf-8")  # type: ignore[operator]
            dst.writestr(item, data)
    return out


def codes(report: export_check.CheckReport, severity: str = "FAIL") -> list[str]:
    return [f.code for f in report.findings if f.severity == severity]


def paragraph_xml(xml: str, containing: str) -> str:
    """Return the ``<w:p>`` element of the paragraph whose text contains ``containing``."""
    for match in re.finditer(r"<w:p(?:\s[^>]*)?>.*?</w:p>", xml, re.S):
        if containing in match.group(0):
            return match.group(0)
    raise AssertionError(containing)


def test_a_clean_resume_passes_with_no_findings(tmp_path: Path, contact: Contact) -> None:
    """R10: an exported resume passes with no findings, and the report says what it counted."""
    report = check_docx(
        export(tmp_path, contact, narrative="I run platform teams."), contact=contact
    )

    assert report.passed
    assert report.findings == ()
    assert report.roles == 4
    assert report.words > 50 and report.paragraphs > 10
    assert report.lines()[-1] == "Check PASS: 0 problem(s), 0 warning(s)"


def test_the_report_says_a_docx_page_count_is_not_available(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: no DOCX page count is claimed; the length line gives words and says why."""
    lines = check_docx(export(tmp_path, contact), contact=contact).lines()

    length = next(line for line in lines if line.startswith("Length:"))
    assert "Page count: not available for a DOCX (it isn't rendered here)" in length
    assert "pages" not in length.replace("Page count", "")


def test_the_two_extractions_read_the_same_text_by_different_routes(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: python-docx paragraphs and the raw document.xml agree on a clean file."""
    path = export(tmp_path, contact)

    document_xml, _ = export_check._read_parts(path)
    from_xml = [line for line in export_check._raw_lines(document_xml) if line.strip()]
    from_docx = [p.text for p in docx.Document(str(path)).paragraphs if p.text.strip()]
    assert from_xml == from_docx


def test_any_table_is_a_failure_counted_in_both_extractions(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: a table anywhere fails the check, found by python-docx and by document.xml."""
    path = export(tmp_path, contact)
    document = docx.Document(str(path))
    document.add_table(rows=1, cols=2)
    document.save(str(path))

    report = check_docx(path, contact=contact)

    assert not report.passed
    (finding,) = [f for f in report.findings if f.code == "table"]
    assert finding.message == "1 table(s) found by python-docx, 1 in document.xml"


def test_a_contact_field_missing_from_one_extraction_is_reported_for_that_one(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: text python-docx can't see (in a content control) is missing from python-docx only."""
    path = export(tmp_path, contact)
    hidden = rewrite(
        path,
        lambda xml: xml.replace(
            (p := paragraph_xml(xml, "512 555 0100")),
            f"<w:sdt><w:sdtContent>{p}</w:sdtContent></w:sdt>",
        ),
    )

    report = check_docx(hidden, contact=contact)

    messages = [f.message for f in report.findings if f.code == "contact"]
    assert messages
    assert all("is missing from python-docx" in m for m in messages)
    assert not any("document.xml" in m for m in messages)


def test_a_contact_field_missing_from_both_is_reported_for_both(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: a phone number that is not in the file is missing from both extractions."""
    path = export(tmp_path, contact)
    other = Contact(name=contact.name, email=contact.email, phone="+1 512 555 0199")

    report = check_docx(path, contact=other)

    messages = [f.message for f in report.findings if f.code == "contact"]
    assert "Phone (+1 512 555 0199) is missing from python-docx" in messages
    assert "Phone (+1 512 555 0199) is missing from document.xml" in messages


def test_missing_hyperlinks_are_reported(tmp_path: Path, contact: Contact) -> None:
    """R10: an email or profile URL the file doesn't link to is a failure."""
    path = export(tmp_path, contact)
    other = Contact(name=contact.name, email="someone@example.com", links=contact.links)

    report = check_docx(path, contact=other)

    assert "no hyperlink to mailto:someone@example.com" in [
        f.message for f in report.findings if f.code == "hyperlink"
    ]


def test_a_role_header_separated_from_its_title_line_fails(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: an empty paragraph between a title and its "Employer | dates" line is reported."""
    path = export(tmp_path, contact)
    split = rewrite(
        path,
        lambda xml: xml.replace(
            (p := paragraph_xml(xml, "Tidewell Health | Feb 2016")), f"<w:p/>{p}", 1
        ),
    )

    report = check_docx(split, contact=contact)

    assert not report.passed
    messages = [f.message for f in report.findings if f.code == "role-header"]
    assert any(m.startswith("python-docx:") and "Tidewell Health | Feb 2016" in m for m in messages)
    assert any(m.startswith("document.xml:") for m in messages)


def test_a_date_range_not_attached_to_a_company_fails(tmp_path: Path, contact: Contact) -> None:
    """R10: a date range alone on a line (the employer dropped from the header) is reported."""
    path = export(tmp_path, contact)
    orphan = rewrite(path, lambda xml: xml.replace("Tidewell Health | Feb 2016", "Feb 2016"))

    report = check_docx(orphan, contact=contact)

    assert any(
        f.code == "role-header" and "a date range is not attached to a company" in f.message
        for f in report.findings
    )


def test_a_role_header_count_that_differs_between_extractions_fails(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: a role python-docx can't see but document.xml can makes the counts differ."""
    path = export(tmp_path, contact)
    title = paragraph_xml(document_text(path), "Tidewell Health | Feb 2016")

    def hide(xml: str) -> str:
        start = xml.index(paragraph_xml(xml, "Senior DevOps Engineer"))
        end = xml.index(title) + len(title)
        return (
            xml[:start]
            + "<w:sdt><w:sdtContent>"
            + xml[start:end]
            + "</w:sdtContent></w:sdt>"
            + xml[end:]
        )

    report = check_docx(rewrite(path, hide), contact=contact)

    assert "role-count" in codes(report)
    assert any(
        f.message == "python-docx found 3 role header(s) and document.xml found 4"
        for f in report.findings
    )


def document_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_a_year_before_the_cutoff_fails_only_when_a_cutoff_was_used(
    tmp_path: Path, contact: Contact
) -> None:
    """R10: a resume exported without a cutoff fails a 20-year check; one with it passes."""
    plain = export(tmp_path, contact, name="plain.docx")
    cut = export(tmp_path, contact, cutoff_years=20, name="cut.docx")

    assert check_docx(plain, contact=contact).passed
    failing = check_docx(plain, contact=contact, cutoff_years=20, today=TODAY)
    assert not failing.passed
    years = [f.message for f in failing.findings if f.code == "year"]
    assert any(m.startswith("2005 is before the 2006 cutoff") for m in years)
    assert any("Pinecrest Mills | Sep 2002" in m for m in years)
    assert check_docx(cut, contact=contact, cutoff_years=20, today=TODAY).passed


def test_a_cutoff_needs_today(tmp_path: Path, contact: Contact) -> None:
    """R10: the cutoff is measured from an injected today; omitting it is an error."""
    with pytest.raises(ExportError, match="needs today"):
        check_docx(export(tmp_path, contact), contact=contact, cutoff_years=20)


def test_third_person_pronouns_fail_and_name_the_line(tmp_path: Path, contact: Contact) -> None:
    """R10: he, she, his, her and friends fail the check, naming the line; they does not."""
    path = export(
        tmp_path, contact, narrative="He ran platform teams. His work cut cost. They agree."
    )

    report = check_docx(path, contact=contact)

    (finding,) = [f for f in report.findings if f.code == "pronoun"]
    assert finding.severity == "FAIL"
    assert finding.message == (
        'third-person he, his in: "He ran platform teams. His work cut cost. They agree."'
    )


def test_accepted_false_positive_a_bullet_about_mentoring_her_fails(
    tmp_path: Path, contact: Contact
) -> None:
    """R10 (accepted, ADR-0032): "Mentored her to promotion" is flagged though it is fine."""
    role = parse_dossier(FIXTURES, require_roles=True).chronology[0]
    dossier = Dossier(
        chronology=(
            ChronologyEntry(
                heading=role.heading, bullets=("Mentored her to promotion",), role=role.role
            ),
        )
    )

    report = check_docx(export(tmp_path, contact, dossier=dossier), contact=contact)

    (finding,) = [f for f in report.findings if f.code == "pronoun"]
    assert finding.message == 'third-person her in: "• Mentored her to promotion"'


def test_cliches_are_warnings_that_do_not_fail_the_check(tmp_path: Path, contact: Contact) -> None:
    """R10: filler phrases are listed as warnings; the check still passes."""
    path = export(tmp_path, contact, narrative="I am a Team Player and a results driven leader.")

    report = check_docx(path, contact=contact)

    assert report.passed
    assert sorted(f.message.split(" in:")[0] for f in report.findings) == [
        '"results-driven"',
        '"team player"',
    ]
    assert codes(report, "WARN") == ["cliche", "cliche"]
    assert report.lines()[-1] == "Check PASS: 0 problem(s), 2 warning(s)"


def test_the_cliche_list_is_short_and_generic() -> None:
    """R10: at most 15 phrases, each lowercase, and each also matches with a space for a hyphen."""
    assert len(CLICHE_PHRASES) <= 15
    assert len(set(CLICHE_PHRASES)) == len(CLICHE_PHRASES)
    for phrase in CLICHE_PHRASES:
        assert phrase == phrase.lower()


@pytest.mark.parametrize(
    ("code", "edit"),
    [
        ("textbox", lambda xml: xml.replace("</w:body>", "<w:txbxContent/></w:body>")),
        ("tab", lambda xml: xml.replace("</w:body>", "<w:p><w:r><w:tab/></w:r></w:p></w:body>")),
        (
            "columns",
            lambda xml: re.sub(r"<w:cols\b[^>]*/>", '<w:cols w:num="2" w:space="720"/>', xml),
        ),
    ],
)
def test_text_boxes_tab_characters_and_columns_fail(
    tmp_path: Path, contact: Contact, code: str, edit: object
) -> None:
    """R10: a text box, a tab character or a multi-column section fails the layout check."""
    report = check_docx(rewrite(export(tmp_path, contact), edit), contact=contact)  # type: ignore[arg-type]

    assert code in codes(report)


def test_page_header_or_footer_content_fails(tmp_path: Path, contact: Contact) -> None:
    """R10: text in a page header or footer fails the check."""
    path = export(tmp_path, contact)
    document = docx.Document(str(path))
    document.sections[0].footer.paragraphs[0].text = "Page 1"
    document.save(str(path))

    assert "header-footer" in codes(check_docx(path, contact=contact))


def test_a_document_xml_declaring_a_size_over_the_cap_is_refused_before_it_is_read(
    tmp_path: Path, contact: Contact, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10: a word/document.xml declaring a size over the cap is refused unread."""
    path = tmp_path / "big.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<w:document>" + "x" * 500 + "</w:document>")
    monkeypatch.setattr(export_check, "MAX_PART_BYTES", 100)

    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("a part was opened")

    monkeypatch.setattr(zipfile.ZipFile, "open", refuse)

    with pytest.raises(ExportError) as exc_info:
        check_docx(path, contact=contact)
    assert "part word/document.xml declares 525 bytes, over the 100-byte limit" in str(
        exc_info.value
    )


def test_every_part_is_held_to_the_cap_not_only_document_xml(
    tmp_path: Path, contact: Contact, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10: python-docx would load every part, so any oversized part refuses the file."""
    path = export(tmp_path, contact)
    monkeypatch.setattr(export_check, "MAX_PART_BYTES", 100)

    with pytest.raises(ExportError, match=r"declares \d+ bytes, over the 100-byte limit; not read"):
        check_docx(path, contact=contact)


def test_files_that_are_not_a_docx_are_refused(tmp_path: Path, contact: Contact) -> None:
    """R10: a non-zip file and a zip without word/document.xml are errors, not crashes."""
    not_zip = tmp_path / "a.docx"
    not_zip.write_text("hello", encoding="utf-8")
    no_document = tmp_path / "b.docx"
    with zipfile.ZipFile(no_document, "w") as archive:
        archive.writestr("readme.txt", "x")

    with pytest.raises(ExportError, match="not a readable DOCX"):
        check_docx(not_zip, contact=contact)
    with pytest.raises(ExportError, match=r"no word/document\.xml"):
        check_docx(no_document, contact=contact)


def test_a_file_with_no_role_headers_fails(tmp_path: Path, contact: Contact) -> None:
    """R10: a DOCX with no "Employer | dates" lines at all fails with a clear finding."""
    path = tmp_path / "blank.docx"
    document = docx.Document()
    document.add_paragraph("Jordan Example")
    document.save(str(path))

    assert "role-count" in codes(check_docx(path, contact=contact))


def test_report_to_dict_carries_findings_and_lines(tmp_path: Path, contact: Contact) -> None:
    """R10: the JSON form has the verdict, each finding, the counts and the printable lines."""
    path = export(tmp_path, contact, narrative="She ran things.")

    data = check_docx(path, contact=contact).to_dict()

    assert data["passed"] is False
    assert data["findings"][0]["code"] == "pronoun" and data["findings"][0]["severity"] == "FAIL"
    assert data["roles"] == 4
    assert data["lines"][-1].startswith("Check FAIL: 1 problem(s)")
