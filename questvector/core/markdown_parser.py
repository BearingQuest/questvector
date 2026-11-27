"""Markdown AST parser for the QuestVector dossier documents.

Spec reference: MASTER_DEVELOPER_SPEC.pdf Section 2 describes a Rust-compiled
Wasm "Markdown AST Parser." The spec does not define QuestVector's own
Markdown dialect, so this module documents the schema this implementation
assumes (a deliberate design decision made per the Stage 1 blueprint, since
this build targets a generic/standalone schema rather than any specific
existing document format):

    ## <Heading text>
    - <bullet line>
    - <bullet line>

    ## <Next heading>
    - ...

Rules:
    * A level-2 heading (``## ...``) starts a new section. Its exact meaning
      (a capability *domain*, a chronology *role*, or an impact *grouping*)
      depends on which file it came from.
    * Bullet lines start with ``-``, ``*``, or ``•`` (optionally indented).
    * Blank lines and any other heading level are ignored/skipped rather
      than treated as errors, so lightly-decorated Markdown still parses.
    * Bullets appearing before any heading are grouped under the sentinel
      heading ``"Uncategorized"`` rather than rejected, since a missing
      leading heading is a common, easily-tolerated authoring slip.
    * A file that is empty, whitespace-only, or not valid UTF-8 text is
      treated as malformed and raises :class:`~questvector.exceptions.ParseError`.

Only the Standard Library (``re``, ``pathlib``) is used, per the project's
"stdlib before third-party" standard — no markdown parsing library is pulled
in for what is, in QuestVector's case, a deliberately small and regular
subset of Markdown.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from questvector.config import STOPWORDS
from questvector.core.models import Capability, ChronologyEntry, Dossier, ImpactStatement, Role
from questvector.core.normalize import normalized_tokens
from questvector.exceptions import ParseError

_HEADING_RE = re.compile(r"^#{2}\s+(?P<heading>.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+(?P<text>.+?)\s*$")
_UNCATEGORIZED = "Uncategorized"
# RUF001: the en and em dashes are part of the role heading form (ADR-0032).
_ROLE_RE = re.compile(
    r"^(?P<title>.+?) — (?P<employer>.+) "
    r"\((?P<start>[A-Za-z]+ \d{4})\s*[–-]\s*(?P<end>[A-Za-z]+ \d{4}|Present)\)$",  # noqa: RUF001
    re.IGNORECASE,
)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
ROLE_HEADING_FORM = "Title — Employer (Mon YYYY – Mon YYYY or Present)"  # noqa: RUF001
ROLE_HEADING_EXAMPLE = "Senior SRE — Acme Corp (Jan 2020 – Mar 2023)"  # noqa: RUF001
_MIN_TOKEN_LEN = 2


def tokenize(text: str) -> frozenset[str]:
    """Extract a normalized keyword set from free text.

    Args:
        text: Arbitrary natural-language text (a bullet, a job description,
            etc.).

    Returns:
        A frozenset of normalized tokens with stopwords and single-character
        tokens removed. Normalization (ADR-0027, see
        :mod:`questvector.core.normalize`) lowercases, maps common variants
        such as "CI/CD", "SOC 2" and "K8s" to one form, and drops trailing
        punctuation. It is applied the same way to job descriptions, dossiers,
        and template keywords. This is intentionally a simple, dependency-free
        heuristic (no stemming/lemmatization or POS tagging) — see
        :mod:`questvector.core.matcher` for how it is consumed and where its
        limitations are documented.
    """
    return frozenset(
        token
        for token in normalized_tokens(text)
        if len(token) >= _MIN_TOKEN_LEN and token not in STOPWORDS
    )


def _parse_month_year(text: str) -> date:
    """Parse ``"Mon YYYY"`` (three-letter English month) into the first day of that month."""
    month_name, year = text.split()
    try:
        month = _MONTHS.index(month_name.lower()) + 1
    except ValueError:
        raise ParseError(f'"{month_name}" is not a three-letter month (Jan to Dec)') from None
    return date(int(year), month, 1)


def parse_role_heading(heading: str) -> Role:
    """Parse a Chronology heading in the ``Title — Employer (Mon YYYY - Mon YYYY)`` form.

    Args:
        heading: The heading text, without the leading ``## ``.

    Returns:
        The parsed :class:`Role`. ``Present`` as the end date gives ``end=None``.

    Raises:
        ParseError: If the heading doesn't match the form, uses an unknown month, or
            ends before it starts.
    """
    match = _ROLE_RE.match(heading.strip())
    if match is None:
        raise ParseError(f'does not match "{ROLE_HEADING_FORM}"')
    start = _parse_month_year(match.group("start"))
    end_text = match.group("end")
    end = None if end_text.lower() == "present" else _parse_month_year(end_text)
    if end is not None and end < start:
        raise ParseError("the end date is before the start date")
    return Role(
        title=match.group("title").strip(),
        employer=match.group("employer").strip(),
        start=start,
        end=end,
    )


def _read_text(path: Path) -> str:
    """Read a Markdown file as UTF-8 text.

    Args:
        path: Path to the file to read.

    Returns:
        The file's decoded text content.

    Raises:
        ParseError: If the file does not exist, cannot be read, or is not
            valid UTF-8.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ParseError(
            f"Dossier file not found: {path.name}", context={"path": str(path)}
        ) from exc
    except UnicodeDecodeError as exc:
        raise ParseError(
            f"Dossier file is not valid UTF-8 text: {path.name}",
            context={"path": str(path)},
        ) from exc
    except OSError as exc:
        raise ParseError(
            f"Could not read dossier file: {path.name}",
            context={"path": str(path), "os_error": str(exc)},
        ) from exc
    return content


def _parse_sections(content: str, *, source_name: str) -> list[tuple[str, list[str]]]:
    """Split raw Markdown text into ``(heading, bullets)`` sections.

    Args:
        content: Raw file content.
        source_name: File name, used only for error context.

    Returns:
        A list of ``(heading, bullets)`` tuples in document order. Bullets
        preceding the first heading are grouped under ``"Uncategorized"``.

    Raises:
        ParseError: If the content is empty/whitespace-only, or contains no
            recognizable headings or bullets at all.
    """
    if not content.strip():
        raise ParseError(f"Dossier file is empty: {source_name}", context={"file": source_name})

    sections: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_bullets: list[str] = []

    def _flush() -> None:
        if current_heading is not None:
            sections.append((current_heading, current_bullets.copy()))

    for line in content.splitlines():
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            _flush()
            current_heading = heading_match.group("heading")
            current_bullets = []
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            if current_heading is None:
                current_heading = _UNCATEGORIZED
            current_bullets.append(bullet_match.group("text"))

    _flush()

    if not sections:
        raise ParseError(
            f"No headings or bullet items found in: {source_name}",
            context={"file": source_name},
        )
    return sections


def parse_capabilities(path: Path) -> tuple[Capability, ...]:
    """Parse a ``Capabilities.md`` file into :class:`Capability` entries.

    Each level-2 heading is treated as a capability domain, and each bullet
    beneath it becomes one :class:`Capability` in that domain.

    Args:
        path: Path to the Capabilities Markdown file.

    Returns:
        A tuple of parsed capabilities, in document order.

    Raises:
        ParseError: If the file is missing, unreadable, or contains no
            parsable headings/bullets.
    """
    content = _read_text(path)
    sections = _parse_sections(content, source_name=path.name)
    capabilities: list[Capability] = []
    for domain, bullets in sections:
        for bullet in bullets:
            capabilities.append(Capability(domain=domain, text=bullet, keywords=tokenize(bullet)))
    return tuple(capabilities)


def parse_chronology(path: Path, *, require_roles: bool = False) -> tuple[ChronologyEntry, ...]:
    """Parse a ``Chronology.md`` file into :class:`ChronologyEntry` entries.

    Each level-2 heading is treated as one role/timeframe entry, and its
    bullets are that role's responsibilities/achievements. The heading's words
    (the role title) count as keywords too; Capabilities and Impact headings
    are labels, not claims, and do not. A heading in the
    ``Title — Employer (Mon YYYY - Mon YYYY)`` form is also parsed into
    :attr:`ChronologyEntry.role`, and then only its title and employer count as
    keywords (month names never do).

    Args:
        path: Path to the Chronology Markdown file.
        require_roles: When true (the resume export), every heading must use the
            role form, and a heading that doesn't is an error. When false, any
            heading is accepted and ``role`` is ``None`` for those that don't fit.

    Returns:
        A tuple of parsed chronology entries, in document order.

    Raises:
        ParseError: If the file is missing, unreadable, or contains no
            parsable headings/bullets; or, with ``require_roles``, if any heading
            doesn't use the role form (the error names every such heading).
    """
    content = _read_text(path)
    sections = _parse_sections(content, source_name=path.name)
    entries: list[ChronologyEntry] = []
    problems: list[str] = []
    for heading, bullets in sections:
        role: Role | None = None
        try:
            role = parse_role_heading(heading)
        except ParseError as exc:
            problems.append(f'  - "{heading}": {exc.message}')
        keywords: set[str] = (
            set(tokenize(role.title)) | set(tokenize(role.employer))
            if role
            else set(tokenize(heading))
        )
        for bullet in bullets:
            keywords |= tokenize(bullet)
        entries.append(
            ChronologyEntry(
                heading=heading, bullets=tuple(bullets), keywords=frozenset(keywords), role=role
            )
        )
    if require_roles and problems:
        raise ParseError(
            f"{path.name}: the resume style needs every role heading in the form "
            f'"{ROLE_HEADING_FORM}", for example "{ROLE_HEADING_EXAMPLE}". '
            "These headings don't fit:\n" + "\n".join(problems)
        )
    return tuple(entries)


def parse_impact(path: Path) -> tuple[ImpactStatement, ...]:
    """Parse an ``Impact.md`` file into :class:`ImpactStatement` entries.

    Each level-2 heading groups a set of quantified-impact bullets.

    Args:
        path: Path to the Impact Markdown file.

    Returns:
        A tuple of parsed impact statement groups, in document order.

    Raises:
        ParseError: If the file is missing, unreadable, or contains no
            parsable headings/bullets.
    """
    content = _read_text(path)
    sections = _parse_sections(content, source_name=path.name)
    statements: list[ImpactStatement] = []
    for heading, bullets in sections:
        keywords: set[str] = set()
        for bullet in bullets:
            keywords |= tokenize(bullet)
        statements.append(
            ImpactStatement(heading=heading, bullets=tuple(bullets), keywords=frozenset(keywords))
        )
    return tuple(statements)


def parse_dossier(workspace_dir: Path, *, require_roles: bool = False) -> Dossier:
    """Parse whichever canonical dossier files exist in a workspace.

    Per the Stage 1 blueprint decision, missing dossier files are tolerated
    (a dossier need not have all three documents to be scored) — only a
    *present but malformed* file raises.

    Args:
        workspace_dir: Directory expected to contain ``Capabilities.md``,
            ``Chronology.md``, and/or ``Impact.md``.
        require_roles: Passed to :func:`parse_chronology`; the resume export sets it.

    Returns:
        A :class:`Dossier` built from whichever files were present. Missing
        files contribute empty tuples for their section.

    Raises:
        ParseError: If a present dossier file cannot be parsed.
    """
    from questvector.config import CAPABILITIES_FILENAME, CHRONOLOGY_FILENAME, IMPACT_FILENAME

    capabilities: tuple[Capability, ...] = ()
    chronology: tuple[ChronologyEntry, ...] = ()
    impact: tuple[ImpactStatement, ...] = ()

    capabilities_path = workspace_dir / CAPABILITIES_FILENAME
    if capabilities_path.exists():
        capabilities = parse_capabilities(capabilities_path)

    chronology_path = workspace_dir / CHRONOLOGY_FILENAME
    if chronology_path.exists():
        chronology = parse_chronology(chronology_path, require_roles=require_roles)

    impact_path = workspace_dir / IMPACT_FILENAME
    if impact_path.exists():
        impact = parse_impact(impact_path)

    return Dossier(capabilities=capabilities, chronology=chronology, impact=impact)
