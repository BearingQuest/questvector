"""Compiles a dossier (and optional match result) into a PDF or DOCX bundle.

Spec reference: MASTER_DEVELOPER_SPEC.pdf Section 3 defines ``qv export
--bundle <name> --format <pdf|docx>`` as compiling "tailored resume and
narrative dossier into formatted PDF." The spec's visual theme (Section 1)
is for the interactive HUD application, not the exported document, so —
per the Stage 1 blueprint — this module uses a plain, professional document
layout rather than importing the neon HUD palette into a resume, which
would be inappropriate for a document meant to be read by human recruiters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape, quoteattr

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph as DocxParagraph
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from questvector.core.contact import Contact
from questvector.core.models import CategoryScore, Dossier, MatchResult
from questvector.core.resume import Resume, build_resume
from questvector.exceptions import ExportError

ExportFormat = Literal["pdf", "docx"]
_SUPPORTED_FORMATS: frozenset[str] = frozenset({"pdf", "docx"})
_BUNDLE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _para_text(text: str) -> str:
    """Escape ``text`` so a ReportLab ``Paragraph`` shows it literally.

    ``Paragraph`` reads its text as markup, so a dossier line such as "R&D" or
    "< 100 ms", or an AI summary containing ``<a href=...>``, would otherwise break the
    build or become a link. Every string from the dossier, the match or the model goes
    through this; only markup this module writes itself (``<b>``, ``&bull;``, links to
    the contact details) is added around escaped text.
    """
    return escape(text)


def _match_heading(match_result: MatchResult) -> str:
    """Return the report heading for a match: coverage, or a plain note when nothing is asked."""
    return f"G-Force Match: {match_result.coverage_text()}"


def _coverage_cell(match_result: MatchResult, score: CategoryScore) -> str:
    """Return a category's Coverage table cell; no figure when not asked or not scored."""
    return match_result.category_coverage_text(score)


def _validate_format(fmt: str) -> None:
    """Validate that an export format is supported.

    Args:
        fmt: The requested export format string.

    Raises:
        ExportError: If ``fmt`` is not one of :data:`_SUPPORTED_FORMATS`.
    """
    if fmt not in _SUPPORTED_FORMATS:
        raise ExportError(
            f"Unsupported export format: {fmt!r}",
            context={"supported_formats": sorted(_SUPPORTED_FORMATS)},
        )


def resolve_bundle_path(output_dir: Path, bundle_name: str, fmt: str) -> Path:
    """Build the output path for a bundle, refusing names that could leave ``output_dir``.

    The desktop bridge and ``qv export`` both call this before writing anything.

    Args:
        output_dir: The directory bundles are written to (``<workspace>/bundles``).
        bundle_name: The requested name, without extension.
        fmt: The export format, used as the file extension.

    Returns:
        ``output_dir / "<bundle_name>.<fmt>"``.

    Raises:
        ExportError: If the name is not 1-64 letters, digits, dots, dashes or
            underscores starting with a letter or digit, is ``.`` or ``..``, or
            the resolved path would fall outside ``output_dir``.
    """
    # fullmatch, not match with "$": "$" would accept a trailing newline.
    if bundle_name in {".", ".."} or _BUNDLE_NAME_PATTERN.fullmatch(bundle_name) is None:
        raise ExportError(
            "Bundle name must be 1-64 letters, digits, dots, dashes or underscores, "
            "starting with a letter or digit (no slashes or spaces)",
            context={"bundle_name": bundle_name},
        )
    base = output_dir.resolve()
    path = output_dir / f"{bundle_name}.{fmt}"
    if not path.resolve().is_relative_to(base):
        raise ExportError(
            "Bundle name would write outside the bundles folder",
            context={"bundle_name": bundle_name},
        )
    return path


def export_bundle(
    dossier: Dossier,
    output_path: Path,
    *,
    fmt: ExportFormat,
    match_result: MatchResult | None = None,
    narrative: str | None = None,
    title: str = "Career Dossier",
) -> Path:
    """Compile a dossier bundle into a PDF or DOCX file.

    Args:
        dossier: The parsed dossier to render.
        output_path: Destination file path. Parent directories must exist.
        fmt: ``"pdf"`` or ``"docx"``.
        match_result: Optional G-Force match result to include as a
            summary/gaps section.
        narrative: Optional LLM-generated narrative summary paragraph (see
            :mod:`questvector.core.llm`) to include at the top of the
            document.
        title: Document title.

    Returns:
        ``output_path``, on success.

    Raises:
        ExportError: If ``fmt`` is unsupported, or the underlying
            PDF/DOCX library raises while building the document.
    """
    _validate_format(fmt)
    try:
        if fmt == "pdf":
            _export_pdf(
                dossier, output_path, match_result=match_result, narrative=narrative, title=title
            )
        else:
            _export_docx(
                dossier, output_path, match_result=match_result, narrative=narrative, title=title
            )
    except ExportError:
        raise
    except Exception as exc:
        # third-party rendering-library failure into our own exception type
        # so callers only ever need to catch QuestVectorError subclasses.
        raise ExportError(
            f"Failed to export {fmt} bundle: {exc}",
            context={"output_path": str(output_path), "format": fmt},
        ) from exc
    return output_path


def _export_pdf(
    dossier: Dossier,
    output_path: Path,
    *,
    match_result: MatchResult | None,
    narrative: str | None,
    title: str,
) -> None:
    """Render the dossier bundle as a PDF using reportlab.

    Args:
        dossier: The parsed dossier to render.
        output_path: Destination PDF path.
        match_result: Optional match result to summarize.
        narrative: Optional narrative summary paragraph.
        title: Document title.
    """
    styles = getSampleStyleSheet()
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]
    title_style = ParagraphStyle("DossierTitle", parent=styles["Title"], spaceAfter=12)

    story: list[Flowable] = [Paragraph(_para_text(title), title_style)]

    if narrative:
        story.append(Paragraph("Summary", heading_style))
        story.append(Paragraph(_para_text(narrative), body_style))
        story.append(Spacer(1, 0.2 * inch))

    if match_result is not None:
        story.append(Paragraph(_para_text(_match_heading(match_result)), heading_style))
        story.append(
            Paragraph(_para_text(f"Relevance: {match_result.relevance_text()}"), body_style)
        )
        story.append(Paragraph(_para_text(match_result.counts_text()), body_style))
        if match_result.low_relevance:
            story.append(Paragraph(_para_text(match_result.relevance_note()), body_style))
        table_data = [["Category", "Weight", "Coverage", "Asked"]]
        for score in match_result.category_scores:
            table_data.append(
                [
                    score.name,
                    f"{score.weight:.2f}",
                    _coverage_cell(match_result, score),
                    score.counts_text(),
                ]
            )
        table = Table(table_data, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(table)
        if match_result.gaps:
            story.append(Spacer(1, 0.1 * inch))
            story.append(Paragraph(_para_text("Gaps: " + ", ".join(match_result.gaps)), body_style))
        story.append(Spacer(1, 0.2 * inch))

    if dossier.capabilities:
        story.append(Paragraph("Capabilities", heading_style))
        by_domain: dict[str, list[str]] = {}
        for capability in dossier.capabilities:
            by_domain.setdefault(capability.domain, []).append(capability.text)
        for domain, items in by_domain.items():
            story.append(Paragraph(f"<b>{_para_text(domain)}</b>", body_style))
            for item in items:
                story.append(Paragraph(f"&bull; {_para_text(item)}", body_style))
        story.append(Spacer(1, 0.2 * inch))

    if dossier.chronology:
        story.append(Paragraph("Chronology", heading_style))
        for entry in dossier.chronology:
            story.append(Paragraph(f"<b>{_para_text(entry.heading)}</b>", body_style))
            for bullet in entry.bullets:
                story.append(Paragraph(f"&bull; {_para_text(bullet)}", body_style))
        story.append(Spacer(1, 0.2 * inch))

    if dossier.impact:
        story.append(Paragraph("Impact", heading_style))
        for stmt in dossier.impact:
            story.append(Paragraph(f"<b>{_para_text(stmt.heading)}</b>", body_style))
            for bullet in stmt.bullets:
                story.append(Paragraph(f"&bull; {_para_text(bullet)}", body_style))

    doc = SimpleDocTemplate(str(output_path), pagesize=LETTER)
    doc.build(story)


def _export_docx(
    dossier: Dossier,
    output_path: Path,
    *,
    match_result: MatchResult | None,
    narrative: str | None,
    title: str,
) -> None:
    """Render the dossier bundle as a DOCX using python-docx.

    Args:
        dossier: The parsed dossier to render.
        output_path: Destination DOCX path.
        match_result: Optional match result to summarize.
        narrative: Optional narrative summary paragraph.
        title: Document title.
    """
    document = Document()
    document.add_heading(title, level=0)

    if narrative:
        document.add_heading("Summary", level=1)
        document.add_paragraph(narrative)

    if match_result is not None:
        document.add_heading(_match_heading(match_result), level=1)
        document.add_paragraph(f"Relevance: {match_result.relevance_text()}")
        document.add_paragraph(match_result.counts_text())
        if match_result.low_relevance:
            document.add_paragraph(match_result.relevance_note())
        table = document.add_table(rows=1, cols=4)
        table.style = "Light Grid"
        header = table.rows[0].cells
        for cell, label in zip(header, ("Category", "Weight", "Coverage", "Asked"), strict=True):
            cell.text = label
        for score in match_result.category_scores:
            row = table.add_row().cells
            row[0].text = score.name
            row[1].text = f"{score.weight:.2f}"
            row[2].text = _coverage_cell(match_result, score)
            row[3].text = score.counts_text()
        if match_result.gaps:
            gaps_paragraph = document.add_paragraph()
            gaps_run = gaps_paragraph.add_run("Gaps: " + ", ".join(match_result.gaps))
            gaps_run.font.size = Pt(10)

    if dossier.capabilities:
        document.add_heading("Capabilities", level=1)
        by_domain: dict[str, list[str]] = {}
        for capability in dossier.capabilities:
            by_domain.setdefault(capability.domain, []).append(capability.text)
        for domain, items in by_domain.items():
            document.add_heading(domain, level=2)
            for item in items:
                document.add_paragraph(item, style="List Bullet")

    if dossier.chronology:
        document.add_heading("Chronology", level=1)
        for entry in dossier.chronology:
            document.add_heading(entry.heading, level=2)
            for bullet in entry.bullets:
                document.add_paragraph(bullet, style="List Bullet")

    if dossier.impact:
        document.add_heading("Impact", level=1)
        for stmt in dossier.impact:
            document.add_heading(stmt.heading, level=2)
            for bullet in stmt.bullets:
                document.add_paragraph(bullet, style="List Bullet")

    document.save(str(output_path))


@dataclass(frozen=True, slots=True)
class ResumeExport:
    """The result of a resume-style export.

    Attributes:
        path: The file written.
        notes: What was left out or moved, for the user; never written into the file.
        pdf_pages: The page count, for a PDF (ReportLab knows it); ``None`` for a DOCX,
            which isn't rendered here, so its page count can't be known.
    """

    path: Path
    notes: tuple[str, ...] = field(default_factory=tuple)
    pdf_pages: int | None = None


def export_resume(
    dossier: Dossier,
    contact: Contact,
    output_path: Path,
    *,
    fmt: ExportFormat,
    narrative: str | None = None,
    cutoff_years: int | None = None,
    today: date,
) -> ResumeExport:
    """Write a resume-style PDF or DOCX (PRD R9, ADR-0032).

    One column; no tables, text boxes, columns, tab stops, headers or footers; a title
    line then "Employer | Mon YYYY - Mon YYYY" per role; the summary (when given) at the
    top; no match score, table or gaps. See :func:`questvector.core.resume.build_resume`
    for what is included.

    Args:
        dossier: A dossier parsed with ``require_roles=True``.
        contact: Validated contact details (they never leave the machine).
        output_path: Destination file path. Parent directories must exist.
        fmt: ``"pdf"`` or ``"docx"``.
        narrative: The cleaned summary paragraph (see :mod:`questvector.core.guardrails`).
        cutoff_years: When set, move roles that ended more than this many years before
            ``today`` to a dateless Earlier Career line.
        today: The date the cutoff is measured from (injected so tests don't use the clock).

    Returns:
        A :class:`ResumeExport` with the path, the notes and, for a PDF, the page count.

    Raises:
        ExportError: If the format is unsupported, the dossier can't make a resume, a
            role conflicts with the cutoff, or the rendering library fails.
    """
    _validate_format(fmt)
    resume = build_resume(
        dossier, contact, narrative=narrative, cutoff_years=cutoff_years, today=today
    )
    pages: int | None = None
    try:
        if fmt == "pdf":
            pages = _resume_pdf(resume, output_path)
        else:
            _resume_docx(resume, output_path)
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(
            f"Failed to export {fmt} resume: {exc}",
            context={"output_path": str(output_path), "format": fmt},
        ) from exc
    return ResumeExport(path=output_path, notes=resume.notes, pdf_pages=pages)


def _add_hyperlink(paragraph: DocxParagraph, text: str, url: str) -> None:
    """Append a real hyperlink (an external relationship) to a DOCX paragraph."""
    relationship_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(color)
    properties.append(underline)
    run.append(properties)
    text_element = OxmlElement("w:t")
    text_element.set(qn("xml:space"), "preserve")
    text_element.text = text
    run.append(text_element)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _resume_docx(resume: Resume, output_path: Path) -> None:
    """Lay out the resume as a DOCX: Normal paragraphs and plain headings only."""
    document = Document()
    section = document.sections[0]
    section.left_margin = section.right_margin = Inches(0.75)
    section.top_margin = section.bottom_margin = Inches(0.75)
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    name = document.add_paragraph()
    name_run = name.add_run(resume.contact.name)
    name_run.bold = True
    name_run.font.size = Pt(16)
    name.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for line in resume.contact_lines():
        paragraph = document.add_paragraph()
        for index, (text, href) in enumerate(line):
            if index:
                paragraph.add_run(" | ")
            if href:
                _add_hyperlink(paragraph, text, href)
            else:
                paragraph.add_run(text)

    def heading(text: str) -> None:
        document.add_heading(text, level=1)

    def bullet(text: str) -> None:
        document.add_paragraph(f"• {text}")

    if resume.summary:
        heading("Summary")
        document.add_paragraph(resume.summary)
    if resume.capabilities:
        heading("Core Capabilities")
        document.add_paragraph(" | ".join(resume.capabilities))
    heading("Experience")
    for role in resume.roles:
        title = document.add_paragraph()
        title_run = title.add_run(role.title)
        title_run.bold = True
        title_run.font.color.rgb = RGBColor(0, 0, 0)
        document.add_paragraph(role.header_line())
        for text in role.bullets:
            bullet(text)
    if resume.earlier:
        heading("Earlier Career")
        document.add_paragraph("; ".join(resume.earlier))
    if resume.results:
        heading("Selected Results")
        for text in resume.results:
            bullet(text)
    document.save(str(output_path))


def _resume_pdf(resume: Resume, output_path: Path) -> int:
    """Lay out the resume as a PDF of plain paragraphs; return the page count."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle("ResumeBody", parent=styles["BodyText"], fontSize=10.5, leading=13)
    name_style = ParagraphStyle(
        "ResumeName", parent=styles["Title"], fontSize=18, alignment=0, spaceAfter=4
    )
    heading_style = ParagraphStyle("ResumeHeading", parent=styles["Heading2"], spaceBefore=10)

    def link(text: str, href: str) -> str:
        return f'<a href={quoteattr(href)} color="blue">{_para_text(text)}</a>'

    story: list[Flowable] = [Paragraph(_para_text(resume.contact.name), name_style)]
    for line in resume.contact_lines():
        parts = [link(text, href) if href else _para_text(text) for text, href in line]
        story.append(Paragraph(" | ".join(parts), body))
    if resume.summary:
        story.append(Paragraph("Summary", heading_style))
        story.append(Paragraph(_para_text(resume.summary), body))
    if resume.capabilities:
        story.append(Paragraph("Core Capabilities", heading_style))
        story.append(Paragraph(_para_text(" | ".join(resume.capabilities)), body))
    story.append(Paragraph("Experience", heading_style))
    for role in resume.roles:
        story.append(Paragraph(f"<b>{_para_text(role.title)}</b>", body))
        story.append(Paragraph(_para_text(role.header_line()), body))
        for text in role.bullets:
            story.append(Paragraph(f"&bull; {_para_text(text)}", body))
    if resume.earlier:
        story.append(Paragraph("Earlier Career", heading_style))
        story.append(Paragraph(_para_text("; ".join(resume.earlier)), body))
    if resume.results:
        story.append(Paragraph("Selected Results", heading_style))
        for text in resume.results:
            story.append(Paragraph(f"&bull; {_para_text(text)}", body))
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    doc.build(story)
    return int(doc.page)
