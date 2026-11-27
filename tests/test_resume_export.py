"""Tests for the resume-style export: questvector.core.resume and exporter.export_resume (R9).

Synthetic data only (tests/fixtures/resume). "Today" is always passed in, never read.
"""

# ruff: noqa: RUF001, RUF002
# The en dash is part of the role heading and date range forms under test.
from __future__ import annotations

import re
import zipfile
from datetime import date
from pathlib import Path

import docx
import pytest
from export_text import docx_text, pdf_text

from questvector.core.contact import Contact, parse_contact
from questvector.core.exporter import export_bundle, export_resume
from questvector.core.markdown_parser import parse_dossier
from questvector.core.models import Capability, ChronologyEntry, Dossier, ImpactStatement, Role
from questvector.core.resume import build_resume, cutoff_date, validate_cutoff_years
from questvector.exceptions import ExportError

FIXTURES = Path(__file__).parent / "fixtures" / "resume"
TODAY = date(2026, 11, 27)
DASH = "–"


@pytest.fixture()
def dossier() -> Dossier:
    return parse_dossier(FIXTURES, require_roles=True)


@pytest.fixture()
def contact() -> Contact:
    return parse_contact(FIXTURES / "Contact.md")


def make_docx(
    tmp_path: Path,
    dossier: Dossier,
    contact: Contact,
    *,
    narrative: str | None = None,
    cutoff_years: int | None = None,
    today: date = TODAY,
) -> Path:
    path = tmp_path / "resume.docx"
    export_resume(
        dossier,
        contact,
        path,
        fmt="docx",
        narrative=narrative,
        cutoff_years=cutoff_years,
        today=today,
    )
    return path


def paragraphs(path: Path) -> list[str]:
    return [p.text for p in docx.Document(str(path)).paragraphs if p.text.strip()]


def shown_text(path: Path) -> str:
    """A PDF's text with ReportLab's per-run ``) Tj (`` breaks (at "&", "<") joined back up."""
    return re.sub(r"\)\s*Tj\s*\(", "", pdf_text(path))


def document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_resume_docx_has_no_table_text_box_column_tab_header_or_footer(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: single column; no tables, text boxes, columns, tab stops, headers or footers."""
    path = make_docx(tmp_path, dossier, contact, narrative="I run platform teams.")

    xml = document_xml(path)
    for tag in ("<w:tbl>", "<w:tbl ", "<w:txbxContent", "<w:tab/>", "<w:tab ", "<w:tabs>"):
        assert tag not in xml, tag
    assert not re.search(r'<w:cols\b[^>]*w:num="(?:[2-9]|\d\d)"', xml)
    assert "w:headerReference" not in xml
    assert "w:footerReference" not in xml
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    assert not [n for n in names if re.match(r"word/(header|footer)\d*\.xml", n)]
    assert docx.Document(str(path)).tables == []


def test_each_role_is_a_title_line_then_employer_pipe_dates(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: a title line, then "Employer | Mon YYYY – Mon YYYY", with the employer on every role."""
    lines = paragraphs(make_docx(tmp_path, dossier, contact))

    expected = [
        ("Engineering Manager, Platform", f"Larkspur Freight | Mar 2021 {DASH} Present"),
        ("Senior DevOps Engineer", f"Tidewell Health | Feb 2016 {DASH} Feb 2021"),
        ("Systems Administrator", f"Harbor Light Logistics | Jun 2008 {DASH} Jan 2016"),
        ("Junior Systems Administrator", f"Pinecrest Mills | Sep 2002 {DASH} May 2006"),
    ]
    for title, header in expected:
        assert lines[lines.index(title) + 1] == header
    titles = [lines.index(title) for title, _ in expected]
    assert titles == sorted(titles), "roles are newest first"


def test_contact_block_is_first_and_email_and_profiles_are_real_hyperlinks(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: name and contact lines lead; email and profile URLs are hyperlink relationships."""
    path = make_docx(tmp_path, dossier, contact)

    lines = paragraphs(path)
    assert lines[0] == "Jordan Example"
    assert lines[1] == "Austin, TX | jordan.example@example.com | +1 512 555 0100"
    assert lines[2] == (
        "https://www.linkedin.com/in/jordan-example | https://github.com/jordan-example"
    )
    with zipfile.ZipFile(path) as archive:
        rels = archive.read("word/_rels/document.xml.rels").decode("utf-8")
    for target in (
        "mailto:jordan.example@example.com",
        "https://www.linkedin.com/in/jordan-example",
        "https://github.com/jordan-example",
    ):
        assert re.search(rf'Target="{re.escape(target)}"[^>]*TargetMode="External"', rels), target
    assert document_xml(path).count("<w:hyperlink ") == 3


def test_summary_sits_above_experience_and_is_absent_when_not_given(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: the summary, when generated, is at the top, right after the contact block."""
    with_summary = paragraphs(
        make_docx(tmp_path, dossier, contact, narrative="I run platform teams on AWS.")
    )
    without = paragraphs(make_docx(tmp_path, dossier, contact))

    assert with_summary[3:5] == ["Summary", "I run platform teams on AWS."]
    assert with_summary.index("Summary") < with_summary.index("Experience")
    assert "Summary" not in without


def test_resume_has_no_match_score_table_or_gaps(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: no match score, category table or gaps anywhere in the resume, in either format."""
    docx_path = make_docx(tmp_path, dossier, contact)
    pdf_path = tmp_path / "resume.pdf"
    export_resume(dossier, contact, pdf_path, fmt="pdf", today=TODAY)

    for text in (docx_text(docx_path), pdf_text(pdf_path)):
        for word in ("G-Force", "Gaps", "Coverage", "Category", "Weight", "asked"):
            assert word not in text, word


def test_capabilities_are_domain_names_only_and_impact_is_one_bullet_per_group(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: Core Capabilities lists domain names with no bullet text; results are short."""
    lines = paragraphs(make_docx(tmp_path, dossier, contact))

    core = lines[lines.index("Core Capabilities") + 1]
    assert core.startswith("Cloud Infrastructure | CI/CD Automation")
    assert "Terraform" not in core
    results = lines[lines.index("Selected Results") + 1 :]
    assert results == ["• Cut annual AWS spend by 31%", "• Raised uptime from 99.5% to 99.95%"]


def test_without_a_cutoff_every_role_keeps_its_dates(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: the cutoff is off by default; all roles are dated and nothing is left out."""
    resume = build_resume(dossier, contact, narrative=None, cutoff_years=None, today=TODAY)
    lines = paragraphs(make_docx(tmp_path, dossier, contact))

    assert "Earlier Career" not in lines
    assert f"Pinecrest Mills | Sep 2002 {DASH} May 2006" in lines
    assert "• Moved the data center to a colocation facility in 2005" in lines
    assert resume.notes == ()


def test_cutoff_moves_old_roles_to_one_dateless_line_and_no_old_year_remains(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: with a 20-year cutoff, a role that ended before Nov 2006 moves to Earlier Career."""
    path = make_docx(tmp_path, dossier, contact, cutoff_years=20)

    lines = paragraphs(path)
    assert (
        lines[lines.index("Earlier Career") + 1] == "Junior Systems Administrator, Pinecrest Mills"
    )
    assert "Pinecrest Mills" not in "".join(line for line in lines if "|" in line), (
        "no dated header for it"
    )
    visible = " ".join(re.findall(r"<w:t[ >][^<]*", document_xml(path)) + lines)
    old_years = [y for y in re.findall(r"\b(?:19|20)\d{2}\b", visible) if int(y) < 2006]
    assert old_years == []
    assert "• Moved the data center to a colocation facility in 2005" not in lines


def test_cutoff_reports_what_it_moved_and_left_out(dossier: Dossier, contact: Contact) -> None:
    """R9: the user is told about moved roles and omitted lines (never written into the file)."""
    resume = build_resume(dossier, contact, narrative=None, cutoff_years=20, today=TODAY)

    assert resume.earlier == ("Junior Systems Administrator, Pinecrest Mills",)
    assert [r.employer for r in resume.roles] == [
        "Larkspur Freight",
        "Tidewell Health",
        "Harbor Light Logistics",
    ]
    assert "Moved 1 role(s) that ended before the cutoff to Earlier Career" in resume.notes
    assert "Left out 1 line(s) that mention a year before 2006" in resume.notes


def test_cutoff_is_measured_on_the_end_month_against_the_injected_today(contact: Contact) -> None:
    """R9: today is injected; a role ending before the cutoff month moves, one in it stays."""

    def one_role(end: date) -> Dossier:
        role = Role("Lead", "Acme", date(2006, 1, 1), end)
        return Dossier(
            chronology=(ChronologyEntry(heading="Lead — Acme", bullets=("x",), role=role),)
        )

    oct_2006 = build_resume(
        one_role(date(2006, 10, 1)), contact, narrative=None, cutoff_years=20, today=TODAY
    )
    nov_2006 = build_resume(
        one_role(date(2006, 11, 1)), contact, narrative=None, cutoff_years=20, today=TODAY
    )
    later = build_resume(
        one_role(date(2006, 11, 1)),
        contact,
        narrative=None,
        cutoff_years=20,
        today=date(2026, 12, 1),
    )

    assert oct_2006.earlier == ("Lead, Acme",)
    assert nov_2006.earlier == ()
    assert later.earlier == ("Lead, Acme",)
    assert cutoff_date(date(2028, 2, 29), 1) == date(2027, 2, 28)


def test_summary_sentences_with_a_year_before_the_cutoff_are_left_out(
    dossier: Dossier, contact: Contact
) -> None:
    """R9: no year before the cutoff appears anywhere, including the summary."""
    resume = build_resume(
        dossier,
        contact,
        narrative="I started in 2001. I run platform teams.",
        cutoff_years=20,
        today=TODAY,
    )

    assert resume.summary == "I run platform teams."


def test_a_role_that_straddles_the_cutoff_is_refused_by_name(
    tmp_path: Path, contact: Contact
) -> None:
    """R9: a kept role that started before the cutoff year is refused, naming its heading."""
    (tmp_path / "Chronology.md").write_text(
        "## Platform Lead — Acme (Mar 2003 – Dec 2010)\n- Ran things\n", encoding="utf-8"
    )
    dossier = parse_dossier(tmp_path, require_roles=True)

    with pytest.raises(ExportError, match=r"Platform Lead — Acme \(Mar 2003"):
        build_resume(dossier, contact, narrative=None, cutoff_years=20, today=TODAY)


def test_a_year_before_the_cutoff_in_a_kept_title_is_refused(contact: Contact) -> None:
    """R9: a pre-cutoff year in a kept role's own title can't be dropped, so the export refuses."""
    bad = ChronologyEntry(
        heading="1999 Migration Lead — Acme (Mar 2021 – Present)",
        bullets=("x",),
        role=Role("1999 Migration Lead", "Acme", date(2021, 3, 1), None),
    )

    with pytest.raises(ExportError, match="year before 2006"):
        build_resume(
            Dossier(chronology=(bad,)), contact, narrative=None, cutoff_years=20, today=TODAY
        )


def test_role_bullets_are_capped_and_the_cap_is_reported(contact: Contact) -> None:
    """R9: at most 6 bullets per role; the number left out is reported."""
    heading = "Lead — Acme (Jan 2020 – Present)"
    entry = parse_dossier(FIXTURES, require_roles=True).chronology[0]
    role = entry.role
    assert role is not None
    big = ChronologyEntry(
        heading=heading, bullets=tuple(f"bullet {n}" for n in range(9)), role=role
    )

    resume = build_resume(
        Dossier(chronology=(big,)), contact, narrative=None, cutoff_years=None, today=TODAY
    )

    assert len(resume.roles[0].bullets) == 6
    assert "Left out 3 role bullet(s) beyond 6 per role" in resume.notes


def test_resume_needs_roles_in_the_role_form(contact: Contact) -> None:
    """R9: an entry whose heading wasn't parsed into a role can't be exported."""
    with pytest.raises(ExportError, match="role form"):
        build_resume(
            Dossier(chronology=(ChronologyEntry(heading="Acme — SRE (2020-2023)"),)),
            contact,
            narrative=None,
            cutoff_years=None,
            today=TODAY,
        )
    with pytest.raises(ExportError, match="at least one role"):
        build_resume(Dossier(), contact, narrative=None, cutoff_years=None, today=TODAY)


@pytest.mark.parametrize("years", [0, 61, -5, True])
def test_cutoff_years_outside_1_to_60_are_refused(years: int) -> None:
    """R9: the cutoff is a whole number of years from 1 to 60."""
    with pytest.raises(ExportError, match="from 1 to 60"):
        validate_cutoff_years(years)


def test_resume_pdf_has_links_a_page_count_and_the_same_content(
    tmp_path: Path, dossier: Dossier, contact: Contact
) -> None:
    """R9: the PDF resume has real links, reports its page count, and has no table drawing."""
    path = tmp_path / "resume.pdf"
    result = export_resume(
        dossier, contact, path, fmt="pdf", narrative="I run platform teams.", today=TODAY
    )

    text = pdf_text(path)
    assert result.pdf_pages == 1
    assert text.count("/URI (") == 3
    assert "mailto:jordan.example@example.com" in text
    assert "Jordan Example" in text and "Larkspur Freight | Mar 2021" in text
    assert "I run platform teams." in text
    assert (
        export_resume(dossier, contact, tmp_path / "r.docx", fmt="docx", today=TODAY).pdf_pages
        is None
    )


def test_resume_pdf_and_report_pdf_show_markup_characters_as_text(
    tmp_path: Path, contact: Contact
) -> None:
    """R9: "R&D", "< 100 ms" and an <a href> in an untrusted summary render as literal text."""
    trap = '<a href="https://evil.example/x">click</a>'
    dossier = Dossier(
        capabilities=(Capability(domain="R&D", text="Kept latency < 100 ms"),),
        chronology=(
            ChronologyEntry(
                heading="Lead — R&D Labs (Jan 2020 – Present)",
                bullets=("Cut p99 to < 100 ms",),
                role=parse_dossier(FIXTURES, require_roles=True).chronology[0].role,
            ),
        ),
        impact=(ImpactStatement(heading="Impact", bullets=("Saved R&D time",)),),
    )
    resume_pdf = tmp_path / "resume.pdf"
    report_pdf = tmp_path / "report.pdf"
    export_resume(
        dossier, contact, resume_pdf, fmt="pdf", narrative=f"I do R&D. {trap}", today=TODAY
    )
    export_bundle(dossier, report_pdf, fmt="pdf", narrative=f"I do R&D. {trap}")

    for path in (resume_pdf, report_pdf):
        text = shown_text(path)
        assert "R&D" in text, path.name
        assert "&lt;" not in text, path.name
        assert "evil.example" in text, path.name  # shown as text...
        assert "/URI (https://evil.example" not in pdf_text(path), path.name  # ...never a link
    assert "< 100 ms" in shown_text(resume_pdf)
    assert "< 100 ms" in shown_text(report_pdf)
