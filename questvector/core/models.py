"""Core domain models shared across the parser, matcher, templates, and
exporter modules.

All models are immutable, slotted dataclasses: instances are produced once
by a parser/loader and then read by downstream consumers, so there is no
need for mutability and the immutability makes them safe to share across the
CLI, the desktop JS bridge, and background threads without copying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


# UP042: not a StrEnum on purpose. str() of a member stays "AlertLevel.SUCCESS";
# a StrEnum would return the value instead, a behaviour change.
class AlertLevel(str, Enum):  # noqa: UP042
    """Severity levels mapped to the Brand Bible's HUD alert colors.

    Values match spec Section 1: ``SUCCESS`` -> Tactical Green,
    ``WARNING`` -> Afterburner Amber, ``CRITICAL`` -> Lock-On Red.
    ``LOW_RELEVANCE`` (ADR-0033) means the posting asks too little of the
    template to judge; it is shown muted, not as a warning color.
    """

    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"
    LOW_RELEVANCE = "low_relevance"


@dataclass(frozen=True, slots=True)
class Capability:
    """A single capability/skill entry parsed from ``Capabilities.md``.

    Attributes:
        domain: The capability domain heading it was parsed under
            (e.g. "Platform Engineering").
        text: The capability statement itself, verbatim from the bullet.
        keywords: Lowercased, stopword-filtered tokens extracted from
            ``text`` for use by the matching engine.
    """

    domain: str
    text: str
    keywords: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Role:
    """A role's structured fields, parsed from a Chronology heading (ADR-0032).

    The heading form is ``Title — Employer (Mon YYYY - Mon YYYY)`` or ``(... - Present)``.

    Attributes:
        title: The role title (e.g. "Senior DevOps Engineer").
        employer: The employer.
        start: The first day of the start month.
        end: The first day of the end month, or ``None`` for "Present".
    """

    title: str
    employer: str
    start: date
    end: date | None = None


@dataclass(frozen=True, slots=True)
class ChronologyEntry:
    """A single role/timeframe entry parsed from ``Chronology.md``.

    Attributes:
        heading: The raw heading line (e.g. "Acme Corp — Senior SRE
            (2020-2023)").
        bullets: Responsibility/achievement bullet lines under the heading.
        keywords: Lowercased, stopword-filtered tokens extracted from all
            bullets, for use by the matching engine.
        role: The heading parsed into title, employer and dates, when it uses the
            ``Title - Employer (Mon YYYY - Mon YYYY)`` form (ADR-0032); ``None``
            otherwise. Only the resume export needs it.
    """

    heading: str
    bullets: tuple[str, ...] = field(default_factory=tuple)
    keywords: frozenset[str] = field(default_factory=frozenset)
    role: Role | None = None


@dataclass(frozen=True, slots=True)
class ImpactStatement:
    """A single quantified-impact entry parsed from ``Impact.md``.

    Attributes:
        heading: The raw heading line the statement was grouped under.
        bullets: Impact statement bullet lines under the heading.
        keywords: Lowercased, stopword-filtered tokens extracted from all
            bullets, for use by the matching engine.
    """

    heading: str
    bullets: tuple[str, ...] = field(default_factory=tuple)
    keywords: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Dossier:
    """The full parsed dossier: capabilities, chronology, and impact.

    Attributes:
        capabilities: All parsed capability entries.
        chronology: All parsed chronology entries.
        impact: All parsed impact statement entries.
    """

    capabilities: tuple[Capability, ...] = field(default_factory=tuple)
    chronology: tuple[ChronologyEntry, ...] = field(default_factory=tuple)
    impact: tuple[ImpactStatement, ...] = field(default_factory=tuple)

    def all_keywords(self) -> frozenset[str]:
        """Return the union of every keyword across the whole dossier.

        Returns:
            A frozenset of lowercased keyword tokens drawn from
            capabilities, chronology, and impact sections combined.
        """
        keywords: set[str] = set()
        for cap in self.capabilities:
            keywords |= cap.keywords
        for entry in self.chronology:
            keywords |= entry.keywords
        for stmt in self.impact:
            keywords |= stmt.keywords
        return frozenset(keywords)


@dataclass(frozen=True, slots=True)
class JobDescription:
    """A parsed/normalized job description used as the matcher's target.

    Attributes:
        source: Human-readable origin of the text (e.g. a file path or
            "clipboard").
        raw_text: The original, unmodified JD text.
        keywords: Lowercased, stopword-filtered tokens extracted from
            ``raw_text``.
    """

    source: str
    raw_text: str
    keywords: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class TemplateCategory:
    """A single scoring category within a mission template.

    Attributes:
        name: Category label (e.g. "cloud_infrastructure").
        weight: Fractional weight in ``[0.0, 1.0]``; all categories in a
            template should sum to ``config.WEIGHT_SUM_TARGET``.
        keywords: Keywords associated with this category, matched against
            both the dossier and the job description.
    """

    name: str
    weight: float
    keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class MissionTemplate:
    """A community/starter mission template (spec Section 4).

    Schema reconciled between MASTER_DEVELOPER_SPEC.pdf Section 4 (which
    names the templates but not their format) and the community
    ``CONTRIBUTING_TEMPLATES.md`` schema (``mission_id``/``metadata``/
    ``jd_analysis``/``output_formatting``) already published on the
    project's GitHub repo — see :mod:`questvector.core.templates` for the
    full reconciliation notes. ``categories`` (this build's own weighted
    JD-matching dimensions) is kept from the original Stage 1 design rather
    than the community doc's fixed ``narrative_weighting`` three-way split,
    since per-role category keywords are strictly more expressive and this
    is what :mod:`questvector.core.matcher` is built and tested against.

    Attributes:
        template_id: Mission identifier (``mission_id`` in YAML; filename
            stem if omitted).
        title: Human-readable role title.
        categories: Weighted JD-matching scoring categories.
        source_path: Filesystem path the template was loaded from, if any.
        author: Optional contributor attribution.
        version: Optional template version string.
        description: Optional human-readable summary.
        tags: Optional free-form category tags.
        red_flag_phrases: Literal phrases to scan for directly in a job
            description's text (e.g. "unrealistic requirement") — distinct
            from the matcher's own derived, coverage-based red flags.
        gap_coverage_threshold: Category coverage fraction below which a
            whole category is additionally reported as "weak" (see
            :class:`MatchResult.weak_categories`), independent of
            individual missing keywords.
        tone_style: Optional narrative-generation tone hint (e.g.
            "executive-tactical"), passed through to
            :func:`questvector.core.llm.build_narrative_prompt` when set.
        target_page_budget: Optional target page count for exported
            bundles. Captured and validated, but not yet enforced by
            :mod:`questvector.core.exporter` — documented as a known gap
            rather than silently ignored.
    """

    template_id: str
    title: str
    categories: tuple[TemplateCategory, ...] = field(default_factory=tuple)
    source_path: str | None = None
    author: str | None = None
    version: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    red_flag_phrases: tuple[str, ...] = field(default_factory=tuple)
    gap_coverage_threshold: float | None = None
    tone_style: str | None = None
    target_page_budget: int | None = None

    def weight_sum(self) -> float:
        """Return the sum of all category weights.

        Returns:
            The arithmetic sum of ``weight`` across ``categories``.
        """
        return sum(category.weight for category in self.categories)


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """Per-category result from a match run.

    Attributes:
        name: Category name (matches :class:`TemplateCategory.name`).
        weight: The category's weight as used in this match.
        coverage: Fraction ``[0.0, 1.0]`` of the category's keywords found
            in both the dossier and the job description.
        matched_keywords: Keywords present in the JD and satisfied by the
            dossier.
        gap_keywords: Keywords present in the JD but absent from the
            dossier for this category.
    """

    name: str
    weight: float
    coverage: float
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    gap_keywords: tuple[str, ...] = field(default_factory=tuple)

    @property
    def matched_count(self) -> int:
        """Return how many asked keywords the dossier covers (the N of "N of M")."""
        return len(self.matched_keywords)

    @property
    def asked_count(self) -> int:
        """Return how many of the posting's keywords this category asks (the M of "N of M")."""
        return len(self.matched_keywords) + len(self.gap_keywords)

    @property
    def asked(self) -> bool:
        """Return whether the posting asks anything of this category."""
        return self.asked_count > 0

    def counts_text(self) -> str:
        """Return the display text for this category's asked-keyword count.

        Returns:
            ``"N of M asked"``, or ``"not asked (left out of the score)"`` when
            the posting asks nothing of this category (ADR-0033).
        """
        if not self.asked:
            return "not asked (left out of the score)"
        return f"{self.matched_count} of {self.asked_count} asked"


@dataclass(frozen=True, slots=True)
class NegationWarning:
    """A dossier line that negates a skill the match still counted.

    Attributes:
        file: The dossier file the line is in (e.g. ``"Capabilities.md"``).
        heading: The heading the line sits under.
        line: The line's text, verbatim.
        keywords: The matched posting keywords the negation sits next to.
    """

    file: str
    heading: str
    line: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Result of running the Micro-Diff Matching Engine (spec Section 2/3).

    Attributes:
        g_force_score: Coverage: the weighted match percentage over the
            categories the posting asks about, ``0.0``-``100.0`` (ADR-0033).
            It is ``0.0`` when nothing is asked; use :attr:`coverage` to tell
            that apart from a real zero.
        category_scores: Per-category breakdown.
        gaps: Keywords flagged as missing/weak (Afterburner Amber).
        red_flags: Conditions flagged as critical (Lock-On Red) — a
            category with zero coverage and a high template weight, or a
            template-declared ``red_flag_phrases`` entry found verbatim in
            the job description text.
        weak_categories: Category names whose coverage fell below the
            template's ``gap_coverage_threshold`` (when set), reported
            separately from per-keyword ``gaps`` since a category can be
            "weak" overall without every individual keyword being missing.
        alert_level: Overall severity derived from red flags, relevance and the score.
        negation_warnings: Dossier lines that negate a keyword this match
            counted. Display only: they never change the score or alert level.
        template_keyword_count: Distinct keywords the template lists (relevance denominator).
        asked_template_count: Distinct template keywords the posting asks about
            (relevance numerator); a keyword in two categories counts once.
        low_relevance: Whether the posting asks too little of the template
            (ADR-0033). The alert level is ``LOW_RELEVANCE`` unless a red flag
            made it ``CRITICAL``.
    """

    g_force_score: float
    category_scores: tuple[CategoryScore, ...] = field(default_factory=tuple)
    gaps: tuple[str, ...] = field(default_factory=tuple)
    red_flags: tuple[str, ...] = field(default_factory=tuple)
    weak_categories: tuple[str, ...] = field(default_factory=tuple)
    alert_level: AlertLevel = AlertLevel.WARNING
    negation_warnings: tuple[NegationWarning, ...] = field(default_factory=tuple)
    template_keyword_count: int = 0
    asked_template_count: int = 0
    low_relevance: bool = False

    @property
    def asked_category_count(self) -> int:
        """Return how many template categories the posting asks about."""
        return sum(1 for c in self.category_scores if c.asked)

    @property
    def coverage(self) -> float | None:
        """Return the coverage percentage, or ``None`` when no weighted category is asked."""
        if not any(c.asked and c.weight > 0 for c in self.category_scores):
            return None
        return self.g_force_score

    @property
    def relevance(self) -> float | None:
        """Return asked template keywords as a percentage of all of them.

        ``None`` when the template lists no keywords.
        """
        if self.template_keyword_count == 0:
            return None
        return round(self.asked_template_count / self.template_keyword_count * 100.0, 1)

    @property
    def matched_count(self) -> int:
        """Return how many distinct asked keywords the dossier covers.

        A keyword listed by two categories counts once.
        """
        return len({k for c in self.category_scores for k in c.matched_keywords})

    @property
    def asked_count(self) -> int:
        """Return how many distinct posting keywords the template asks about.

        Only keywords the template lists count (a category with no keywords
        asks about every posting keyword), so this is not every word the
        posting uses.
        """
        return len(
            {k for c in self.category_scores for k in (*c.matched_keywords, *c.gap_keywords)}
        )

    def counts_text(self) -> str:
        """Return the display text for the overall asked-keyword count.

        Returns:
            ``"N of M template keywords in this posting are in your dossier"``,
            or a plain note when the template asks nothing of the posting.
        """
        if self.asked_count == 0:
            return "No template keywords found in this posting"
        return (
            f"{self.matched_count} of {self.asked_count} template keywords "
            "in this posting are in your dossier"
        )

    def coverage_text(self) -> str:
        """Return the display text for the coverage number.

        Returns:
            ``"85.9% coverage"``; a plain note when nothing is asked; and
            ``"not scored (low relevance)"`` when the posting asks too little of the
            template, so no coverage percentage is shown for it (ADR-0033). The
            ``coverage`` number stays in ``to_dict`` for readers of the JSON.
        """
        if self.coverage is None:
            return "no template keywords found in this posting"
        if self.low_relevance:
            return "not scored (low relevance)"
        return f"{self.coverage:.1f}% coverage"

    def category_coverage_text(self, score: CategoryScore) -> str:
        """Return a category's coverage for display: a percentage, or ``"-"`` where none is shown.

        A not-asked category, and every category of a low-relevance result, has no figure.
        """
        if not score.asked or self.low_relevance:
            return "-"
        return f"{score.coverage * 100:.0f}%"

    def relevance_text(self) -> str:
        """Return the display text for relevance, e.g. ``"15 of 36 template keywords (42%)"``."""
        if self.relevance is None:
            return "this template lists no keywords"
        return (
            f"{self.asked_template_count} of {self.template_keyword_count} "
            f"template keywords ({self.relevance:.0f}%)"
        )

    def relevance_note(self) -> str:
        """Return the plain-words note for a low-relevance posting, else an empty string."""
        if not self.low_relevance:
            return ""
        if self.asked_template_count == 0:
            return (
                "No template keywords found in this posting, so the template doesn't "
                "apply. Try another template."
            )
        return (
            f"This posting asks little of this template ({self.asked_template_count} of "
            f"{self.template_keyword_count} keywords, {self.asked_category_count} of "
            f"{len(self.category_scores)} categories). Try another template; coverage "
            "only covers what the posting asks."
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable form used by ``qv sync-ast --json`` and the desktop.

        ``g_force_score`` is the coverage over asked categories (ADR-0033);
        ``coverage`` is the same number, or ``None`` when nothing is asked.

        Returns:
            A dict of the score, coverage, relevance, alert level, gaps, red flags,
            weak categories, per-category detail, the asked-keyword counts and the
            negation warnings.
        """
        return {
            "g_force_score": self.g_force_score,
            "coverage": self.coverage,
            "relevance": self.relevance,
            "low_relevance": self.low_relevance,
            "asked_template_count": self.asked_template_count,
            "template_keyword_count": self.template_keyword_count,
            "asked_category_count": self.asked_category_count,
            "coverage_text": self.coverage_text(),
            "category_coverage_texts": [
                self.category_coverage_text(c) for c in self.category_scores
            ],
            "relevance_text": self.relevance_text(),
            "relevance_note": self.relevance_note(),
            "alert_level": self.alert_level.value,
            "gaps": list(self.gaps),
            "red_flags": list(self.red_flags),
            "weak_categories": list(self.weak_categories),
            "categories": [
                {
                    "name": c.name,
                    "weight": c.weight,
                    "coverage": c.coverage,
                    "matched_keywords": list(c.matched_keywords),
                    "gap_keywords": list(c.gap_keywords),
                    "matched_count": c.matched_count,
                    "asked_count": c.asked_count,
                    "counts_text": c.counts_text(),
                }
                for c in self.category_scores
            ],
            "matched_count": self.matched_count,
            "asked_count": self.asked_count,
            "counts_text": self.counts_text(),
            "negation_warnings": [
                {"file": w.file, "heading": w.heading, "line": w.line, "keywords": list(w.keywords)}
                for w in self.negation_warnings
            ],
        }
