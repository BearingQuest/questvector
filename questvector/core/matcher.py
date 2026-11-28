"""Micro-Diff Matching Engine — computes the "G-Force" match score.

Spec reference: MASTER_DEVELOPER_SPEC.pdf Section 2/3 names this component
("Micro-Diff Matching Engine") and its CLI surface (``qv sync-ast``) and
shows a sample output of 92.4%, but never defines the scoring formula. Per
the Stage 1 blueprint, this implementation documents its own algorithm
rather than guessing at an undisclosed one:

Algorithm
    1. The job description and the dossier are both reduced to normalized
       keyword sets via :func:`questvector.core.markdown_parser.tokenize`
       (variants such as "CI/CD", "SOC 2" and "K8s" map to one form, as do the
       template's own keywords when it is loaded; ADR-0027).
    2. For each weighted category in the active :class:`MissionTemplate`:
        a. ``relevant`` = the category's own keywords that also appear in
           the JD (falling back to *all* JD keywords if the category
           declares none, so a template author isn't required to
           enumerate every possible term).
        b. ``matched`` = the subset of ``relevant`` also present anywhere
           in the dossier.
        c. ``coverage`` = ``len(matched) / len(relevant)``. A category with
           nothing relevant is *not asked*: it is left out of the score and
           of its weight total (ADR-0033, which supersedes ADR-0006's rule
           that it counted as full coverage).
    3. The overall G-Force score (coverage) is the sum of
       ``category.weight * coverage`` over the *asked* categories, divided by
       those categories' weights, as a percentage. Relevance is the distinct
       template keywords the JD asks about over all distinct template
       keywords. When too little is asked (fewer than
       :data:`questvector.config.MATCH_MIN_ASKED_KEYWORDS` keywords or
       :data:`questvector.config.MATCH_MIN_ASKED_CATEGORIES` categories, each
       capped by the template's size) the alert level is ``LOW_RELEVANCE``.
    4. A category is a **red flag** (Lock-On Red) when its template weight
       is at least :data:`questvector.config.MATCH_RED_FLAG_WEIGHT_THRESHOLD`
       and its coverage is exactly zero — a heavily weighted requirement the
       dossier says nothing about.
    5. Any keyword in a gap-coverage category (coverage < 1.0) is surfaced
       as a **gap** (Afterburner Amber), deduplicated across categories.
    6. If the template declares ``jd_analysis.red_flag_phrases`` (schema
       from this project's ``CONTRIBUTING_TEMPLATES.md``), each phrase found
       verbatim (case-insensitive) in the job description's raw text is
       also added to ``red_flags`` — independent of dossier coverage,
       matching spec Section 1's brand table entry for Lock-On Red: "Red
       flags in JD."
    7. If the template declares ``jd_analysis.gap_coverage_threshold``, any
       category whose coverage falls below it is reported in
       ``weak_categories``, separately from per-keyword ``gaps``, since a
       category can be "weak" overall without every individual keyword
       being missing.
    8. Display only, never part of the score: each category reports "N of M
       asked" (matched keywords of matched plus gap keywords), and
       :mod:`questvector.core.negation` flags dossier lines that negate a
       matched keyword (ADR-0030).

This is intentionally a transparent, tunable heuristic — not NLP/semantic
matching — so its behavior is fully predictable and testable. Weights are
normalized defensively even if a template's weights do not sum to exactly
1.00, so a borderline-invalid template still produces a sane score rather
than a silently wrong one.
"""

from __future__ import annotations

from questvector.config import (
    MATCH_CRITICAL_SCORE,
    MATCH_MIN_ASKED_CATEGORIES,
    MATCH_MIN_ASKED_KEYWORDS,
    MATCH_RED_FLAG_WEIGHT_THRESHOLD,
    MATCH_WARNING_SCORE,
)
from questvector.core.markdown_parser import tokenize
from questvector.core.models import (
    AlertLevel,
    CategoryScore,
    Dossier,
    JobDescription,
    MatchResult,
    MissionTemplate,
)
from questvector.core.negation import find_negation_warnings
from questvector.exceptions import MatchEngineError


def parse_job_description(raw_text: str, *, source: str = "input") -> JobDescription:
    """Build a :class:`JobDescription` from raw job-posting text.

    Args:
        raw_text: The job description's full text.
        source: A human-readable label for where the text came from (a file
            path, "clipboard", etc.), used only for diagnostics.

    Returns:
        A :class:`JobDescription` with extracted keywords.

    Raises:
        MatchEngineError: If ``raw_text`` is empty or whitespace-only.
    """
    if not raw_text.strip():
        raise MatchEngineError("Job description text is empty", context={"source": source})
    return JobDescription(source=source, raw_text=raw_text, keywords=tokenize(raw_text))


def _score_category(
    category_name: str,
    category_keywords: frozenset[str],
    weight: float,
    jd_keywords: frozenset[str],
    dossier_keywords: frozenset[str],
) -> CategoryScore:
    """Score one template category against a dossier and job description.

    Args:
        category_name: The category's display name.
        category_keywords: Keywords declared on the template category.
        weight: The category's template weight.
        jd_keywords: All keywords extracted from the job description.
        dossier_keywords: All keywords extracted from the dossier.

    Returns:
        A :class:`CategoryScore` describing coverage, matches, and gaps.
    """
    relevant = (category_keywords & jd_keywords) if category_keywords else jd_keywords
    matched = relevant & dossier_keywords
    gap = relevant - matched
    coverage = 1.0 if not relevant else len(matched) / len(relevant)
    return CategoryScore(
        name=category_name,
        weight=weight,
        coverage=coverage,
        matched_keywords=tuple(sorted(matched)),
        gap_keywords=tuple(sorted(gap)),
    )


def run_match(
    dossier: Dossier, job_description: JobDescription, template: MissionTemplate
) -> MatchResult:
    """Run the Micro-Diff Matching Engine and compute a G-Force score.

    Args:
        dossier: The candidate's parsed dossier.
        job_description: The parsed target job description.
        template: The weighted mission template to score against.

    Returns:
        A :class:`MatchResult` with the overall score, per-category
        breakdown, gaps, red flags, and derived alert level.

    Raises:
        MatchEngineError: If the template has no categories to score
            against.
    """
    if not template.categories:
        raise MatchEngineError(
            "Mission template has no categories to score",
            context={"template_id": template.template_id},
        )

    dossier_keywords = dossier.all_keywords()

    category_scores: list[CategoryScore] = []
    for category in template.categories:
        category_scores.append(
            _score_category(
                category.name,
                frozenset(category.keywords),
                category.weight,
                job_description.keywords,
                dossier_keywords,
            )
        )

    # Only categories the posting asks about count; a not-asked category is
    # left out of the score and of the denominator (ADR-0033).
    asked_scores = [score for score in category_scores if score.asked]
    asked_weight = sum(score.weight for score in asked_scores)
    weighted_total = sum(score.weight * score.coverage for score in asked_scores)
    g_force_score = round((weighted_total / asked_weight) * 100.0, 1) if asked_weight > 0 else 0.0

    gaps: set[str] = set()
    red_flags: list[str] = []
    weak_categories: list[str] = []
    for score in category_scores:
        gaps.update(score.gap_keywords)
        if score.weight >= MATCH_RED_FLAG_WEIGHT_THRESHOLD and score.coverage == 0.0:
            red_flags.append(f"No dossier coverage for high-weight category '{score.name}'")
        if (
            template.gap_coverage_threshold is not None
            and score.coverage < template.gap_coverage_threshold
        ):
            weak_categories.append(score.name)

    jd_text_lower = job_description.raw_text.lower()
    for phrase in template.red_flag_phrases:
        if phrase.lower() in jd_text_lower:
            red_flags.append(f"Job description contains flagged phrase: '{phrase}'")

    # Relevance counts distinct template keywords (a keyword in two categories
    # once); the minimums are capped by the template's own size.
    template_keywords = frozenset(k for category in template.categories for k in category.keywords)
    asked_template_count = len(template_keywords & job_description.keywords)
    min_keywords = min(MATCH_MIN_ASKED_KEYWORDS, len(template_keywords))
    min_categories = min(MATCH_MIN_ASKED_CATEGORIES, len(template.categories))
    low_relevance = len(asked_scores) < min_categories or asked_template_count < min_keywords

    if red_flags:
        alert_level = AlertLevel.CRITICAL
    elif low_relevance:
        alert_level = AlertLevel.LOW_RELEVANCE
    elif g_force_score < MATCH_CRITICAL_SCORE:
        alert_level = AlertLevel.CRITICAL
    elif gaps or weak_categories or g_force_score < MATCH_WARNING_SCORE:
        alert_level = AlertLevel.WARNING
    else:
        alert_level = AlertLevel.SUCCESS

    matched_keywords = frozenset(k for score in category_scores for k in score.matched_keywords)

    return MatchResult(
        g_force_score=g_force_score,
        category_scores=tuple(category_scores),
        gaps=tuple(sorted(gaps)),
        red_flags=tuple(red_flags),
        weak_categories=tuple(weak_categories),
        alert_level=alert_level,
        negation_warnings=find_negation_warnings(dossier, matched_keywords),
        template_keyword_count=len(template_keywords),
        asked_template_count=asked_template_count,
        low_relevance=low_relevance,
    )
