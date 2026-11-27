"""Content of the resume-style export (PRD R9, ADR-0032), independent of file format.

:func:`build_resume` turns a dossier, contact details and an optional summary into a
:class:`Resume`: plain data that the PDF and DOCX writers in
:mod:`questvector.core.exporter` lay out the same way. It decides what goes in (and
reports what it left out), and applies the opt-in cutoff.

"Today" is always passed in, so nothing here reads the clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from questvector.core.contact import Contact
from questvector.core.guardrails import split_sentences
from questvector.core.models import ChronologyEntry, Dossier, Role
from questvector.exceptions import ExportError

# RUF001: the en dash is the date range separator the resume style uses (R9).
DATE_RANGE_SEPARATOR = "–"  # noqa: RUF001
MAX_ROLE_BULLETS = 6
MAX_RESULTS = 5
MAX_CAPABILITY_DOMAINS = 8
MIN_CUTOFF_YEARS = 1
MAX_CUTOFF_YEARS = 60
DEFAULT_CUTOFF_YEARS = 20

_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def format_month(day: date | None) -> str:
    """Return ``"Mon YYYY"`` for a date, or ``"Present"`` for ``None``."""
    return "Present" if day is None else f"{_MONTH_NAMES[day.month - 1]} {day.year}"


def validate_cutoff_years(years: int) -> int:
    """Return ``years`` if it is a usable cutoff, else raise.

    Raises:
        ExportError: If ``years`` isn't a whole number from 1 to 60.
    """
    if isinstance(years, bool) or not MIN_CUTOFF_YEARS <= years <= MAX_CUTOFF_YEARS:
        raise ExportError(
            f"The cutoff must be a whole number of years from {MIN_CUTOFF_YEARS} to "
            f"{MAX_CUTOFF_YEARS}, not {years!r}"
        )
    return years


def cutoff_date(today: date, years: int) -> date:
    """Return the date ``years`` years before ``today`` (29 Feb becomes 28 Feb)."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


@dataclass(frozen=True, slots=True)
class ResumeRole:
    """One role as the resume shows it.

    Attributes:
        title: The title line.
        employer: The employer, repeated on every role.
        start: First day of the start month.
        end: First day of the end month, or ``None`` for Present.
        bullets: The bullets shown (already capped).
    """

    title: str
    employer: str
    start: date
    end: date | None
    bullets: tuple[str, ...] = field(default_factory=tuple)

    def header_line(self) -> str:
        """Return ``"Employer | Mon YYYY - Mon YYYY"``."""
        return (
            f"{self.employer} | {format_month(self.start)} "
            f"{DATE_RANGE_SEPARATOR} {format_month(self.end)}"
        )


@dataclass(frozen=True, slots=True)
class Resume:
    """Everything the resume shows, in order.

    Attributes:
        contact: The validated contact details.
        summary: The summary paragraph, when one was generated.
        capabilities: Capability domain names only (no bullet text).
        roles: Experience, newest first.
        earlier: Dateless "Title, Employer" entries for the cutoff's Earlier Career line.
        results: Selected impact bullets.
        notes: What was left out or moved, for the user (never written into the file).
    """

    contact: Contact
    summary: str | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    roles: tuple[ResumeRole, ...] = field(default_factory=tuple)
    earlier: tuple[str, ...] = field(default_factory=tuple)
    results: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def contact_lines(self) -> list[list[tuple[str, str | None]]]:
        """Return the contact block as lines of ``(text, link target or None)`` items.

        Line one is location, email and phone; line two is the profile URLs. The email
        links to ``mailto:`` and each profile URL links to itself.
        """
        first: list[tuple[str, str | None]] = []
        if self.contact.location:
            first.append((self.contact.location, None))
        first.append((self.contact.email, f"mailto:{self.contact.email}"))
        if self.contact.phone:
            first.append((self.contact.phone, None))
        lines = [first]
        if self.contact.links:
            lines.append([(url, url) for _label, url in self.contact.links])
        return lines


def _roles_newest_first(
    entries: tuple[ChronologyEntry, ...],
) -> list[tuple[ChronologyEntry, Role]]:
    """Return ``(entry, role)`` pairs, newest first (Present sorts first)."""
    pairs: list[tuple[ChronologyEntry, Role]] = []
    for entry in entries:
        if entry.role is None:
            raise ExportError("The resume style needs every Chronology heading in the role form")
        pairs.append((entry, entry.role))
    return sorted(pairs, key=lambda pair: (pair[1].end or date.max, pair[1].start), reverse=True)


def build_resume(
    dossier: Dossier,
    contact: Contact,
    *,
    narrative: str | None,
    cutoff_years: int | None,
    today: date,
) -> Resume:
    """Choose the resume's content.

    Args:
        dossier: A dossier parsed with ``require_roles=True``.
        contact: The validated contact details.
        narrative: The cleaned summary paragraph, or ``None``.
        cutoff_years: When set, roles that ended more than this many years before
            ``today`` (measured on the end month) go to a dateless Earlier Career line,
            and no year before the cutoff appears in the resume.
        today: The date to measure the cutoff from.

    Returns:
        The :class:`Resume`.

    Raises:
        ExportError: If the dossier has no roles or a role has no parsed dates; or, with a
            cutoff, if a role's own heading would put a year before the cutoff in the file
            (a role that started before the cutoff but ended after it, or a title or
            employer that contains such a year).
    """
    if not dossier.chronology:
        raise ExportError("The resume style needs at least one role in Chronology.md")
    entries = _roles_newest_first(dossier.chronology)

    notes: list[str] = []
    cutoff = cutoff_date(today, cutoff_years) if cutoff_years is not None else None
    floor = cutoff.year if cutoff else None

    def has_old_year(text: str) -> bool:
        return floor is not None and any(int(y) < floor for y in YEAR_RE.findall(text))

    omitted_for_years = 0

    def keep_lines(lines: list[str]) -> list[str]:
        nonlocal omitted_for_years
        kept = [line for line in lines if not has_old_year(line)]
        omitted_for_years += len(lines) - len(kept)
        return kept

    roles: list[ResumeRole] = []
    earlier: list[str] = []
    omitted_bullets = 0
    for entry, role in entries:
        heading = entry.heading
        label = f"{role.title}, {role.employer}"
        if cutoff and role.end and (role.end.year, role.end.month) < (cutoff.year, cutoff.month):
            if has_old_year(label):
                raise ExportError(
                    f'Role "{heading}" has a year before {floor} in its title or '
                    "employer: change the heading so the resume can leave dates out"
                )
            earlier.append(label)
            continue
        if has_old_year(label):
            raise ExportError(
                f'Role "{heading}" has a year before {floor} in its title or '
                "employer: change the heading so the resume can leave dates out"
            )
        if cutoff and role.start.year < cutoff.year:
            raise ExportError(
                f'Role "{heading}" started before the cutoff year {floor} but is still '
                "inside it: split it into two roles in Chronology.md, or change its dates, "
                "so no year before the cutoff is printed"
            )
        bullets = keep_lines(list(entry.bullets))
        omitted_bullets += max(0, len(bullets) - MAX_ROLE_BULLETS)
        roles.append(
            ResumeRole(
                role.title, role.employer, role.start, role.end, tuple(bullets[:MAX_ROLE_BULLETS])
            )
        )

    domains = list(dict.fromkeys(c.domain for c in dossier.capabilities))
    domains = [d for d in domains if not has_old_year(d)]
    results = keep_lines([group.bullets[0] for group in dossier.impact if group.bullets])

    summary = narrative.strip() if narrative else None
    if summary and floor is not None:
        sentences = split_sentences(summary)
        kept_sentences = keep_lines(sentences)
        summary = " ".join(kept_sentences) or None

    if earlier:
        notes.append(f"Moved {len(earlier)} role(s) that ended before the cutoff to Earlier Career")
    if omitted_bullets:
        notes.append(
            f"Left out {omitted_bullets} role bullet(s) beyond {MAX_ROLE_BULLETS} per role"
        )
    if len(domains) > MAX_CAPABILITY_DOMAINS:
        notes.append(f"Left out {len(domains) - MAX_CAPABILITY_DOMAINS} capability domain(s)")
    if len([g for g in dossier.impact if g.bullets]) > MAX_RESULTS:
        notes.append("Left out impact groups beyond the first " + str(MAX_RESULTS))
    if omitted_for_years:
        notes.append(f"Left out {omitted_for_years} line(s) that mention a year before {floor}")
    return Resume(
        contact=contact,
        summary=summary,
        capabilities=tuple(domains[:MAX_CAPABILITY_DOMAINS]),
        roles=tuple(roles),
        earlier=tuple(earlier),
        results=tuple(results[:MAX_RESULTS]),
        notes=tuple(notes),
    )
