"""Unit tests for questvector.core.matcher."""

from __future__ import annotations

from pathlib import Path

import pytest

import questvector
from questvector.core.markdown_parser import tokenize
from questvector.core.matcher import parse_job_description, run_match
from questvector.core.models import (
    AlertLevel,
    Capability,
    Dossier,
    MatchResult,
    MissionTemplate,
    TemplateCategory,
)
from questvector.core.templates import load_template
from questvector.exceptions import MatchEngineError

_STARTER_DIR = Path(questvector.__file__).parent / "data" / "starter_templates"


def _template(*categories: TemplateCategory, **kwargs: object) -> MissionTemplate:
    return MissionTemplate(template_id="t1", title="Test Template", categories=categories, **kwargs)  # type: ignore[arg-type]


def test_parse_job_description_extracts_keywords() -> None:
    """R3: a job description is turned into keywords to score against."""
    jd = parse_job_description("Senior AWS Kubernetes Engineer", source="test")
    assert "aws" in jd.keywords
    assert jd.source == "test"


def test_parse_job_description_empty_text_raises() -> None:
    with pytest.raises(MatchEngineError):
        parse_job_description("   ", source="test")


def test_run_match_full_coverage_yields_high_score() -> None:
    """R4: scoring rules, full coverage gives a high score."""
    dossier = Dossier(
        capabilities=(
            Capability(domain="Cloud", text="aws terraform", keywords=tokenize("aws terraform")),
        )
    )
    jd = parse_job_description("Looking for AWS and Terraform experience", source="test")
    template = _template(TemplateCategory(name="cloud", weight=1.0, keywords=("aws", "terraform")))

    result = run_match(dossier, jd, template)

    assert result.g_force_score == 100.0
    assert result.gaps == ()
    assert result.red_flags == ()
    assert result.alert_level == AlertLevel.SUCCESS


def test_run_match_zero_coverage_on_heavy_category_is_red_flag() -> None:
    dossier = Dossier(
        capabilities=(
            Capability(
                domain="Other", text="unrelated skills", keywords=tokenize("unrelated skills")
            ),
        )
    )
    jd = parse_job_description("Requires deep Kubernetes and Terraform expertise", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=0.9, keywords=("kubernetes", "terraform"))
    )

    result = run_match(dossier, jd, template)

    assert result.g_force_score < 40.0
    assert len(result.red_flags) == 1
    assert result.alert_level == AlertLevel.CRITICAL


def test_run_match_category_with_no_relevant_keywords_is_left_out_of_the_score() -> None:
    """R4 (ADR-0033): a category nothing in the posting asks about is left out, not full.

    This replaces the ADR-0006 test that pinned such a category at 100.0.
    """
    jd = parse_job_description("Needs aws and welding", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=0.5, keywords=("aws", "azure")),
        TemplateCategory(name="niche", weight=0.5, keywords=("cobol", "mainframe")),
    )

    result = run_match(_dossier_from("Built things on AWS"), jd, template)

    niche = next(c for c in result.category_scores if c.name == "niche")
    assert not niche.asked
    # cloud alone: 1 of 1 asked is covered. Counting niche as full would also give 100.0,
    # so a miss in cloud is what shows the difference:
    miss = run_match(_dossier_from("Built things"), jd, template)
    assert result.g_force_score == 100.0
    assert miss.g_force_score == 0.0
    assert miss.coverage == 0.0


def test_run_match_no_categories_raises() -> None:
    dossier = Dossier()
    jd = parse_job_description("Some text", source="test")
    template = _template()
    with pytest.raises(MatchEngineError):
        run_match(dossier, jd, template)


def test_run_match_normalizes_weights_not_summing_to_one() -> None:
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="aws", keywords=tokenize("aws")),)
    )
    jd = parse_job_description("Needs AWS experience", source="test")
    # Weights sum to 2.0, not 1.0 -- score should still normalize to 100%.
    template = _template(TemplateCategory(name="cloud", weight=2.0, keywords=("aws",)))

    result = run_match(dossier, jd, template)

    assert result.g_force_score == 100.0


def test_run_match_partial_coverage_produces_gaps() -> None:
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="aws", keywords=tokenize("aws")),)
    )
    jd = parse_job_description("Needs AWS and Kubernetes experience", source="test")
    template = _template(TemplateCategory(name="cloud", weight=1.0, keywords=("aws", "kubernetes")))

    result = run_match(dossier, jd, template)

    assert 0.0 < result.g_force_score < 100.0
    assert "kubernetes" in result.gaps


def test_run_match_red_flag_phrase_found_in_jd_text() -> None:
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="aws", keywords=tokenize("aws")),)
    )
    jd = parse_job_description(
        "Needs AWS experience. Note: candidate must wear many hats.", source="test"
    )
    template = _template(
        TemplateCategory(name="cloud", weight=1.0, keywords=("aws",)),
        red_flag_phrases=("wear many hats",),
    )

    result = run_match(dossier, jd, template)

    assert any("wear many hats" in flag for flag in result.red_flags)


def test_run_match_red_flag_phrase_absent_from_jd_text_no_flag() -> None:
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="aws", keywords=tokenize("aws")),)
    )
    jd = parse_job_description("Needs AWS experience, standard schedule.", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=1.0, keywords=("aws",)),
        red_flag_phrases=("wear many hats",),
    )

    result = run_match(dossier, jd, template)

    assert result.red_flags == ()


def test_run_match_red_flag_phrase_is_case_insensitive() -> None:
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="aws", keywords=tokenize("aws")),)
    )
    jd = parse_job_description("Needs AWS experience. Must WEAR MANY HATS daily.", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=1.0, keywords=("aws",)),
        red_flag_phrases=("wear many hats",),
    )

    result = run_match(dossier, jd, template)

    assert len(result.red_flags) == 1


def test_run_match_weak_categories_below_threshold() -> None:
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="aws", keywords=tokenize("aws")),)
    )
    jd = parse_job_description("Needs AWS Terraform Kubernetes Docker experience", source="test")
    template = _template(
        TemplateCategory(
            name="cloud", weight=1.0, keywords=("aws", "terraform", "kubernetes", "docker")
        ),
        gap_coverage_threshold=0.5,
    )

    result = run_match(dossier, jd, template)

    # Only 1 of 4 keywords covered (25%), below the 0.5 threshold.
    assert "cloud" in result.weak_categories


def test_run_match_no_weak_categories_when_threshold_not_set() -> None:
    dossier = Dossier()
    jd = parse_job_description("Needs AWS Terraform experience", source="test")
    template = _template(TemplateCategory(name="cloud", weight=1.0, keywords=("aws", "terraform")))

    result = run_match(dossier, jd, template)

    assert result.weak_categories == ()


def test_run_match_weak_category_triggers_warning_alert_even_without_gaps_or_red_flags() -> None:
    # High overall score (single fully-relevant keyword covered) but the
    # template still flags this category as weak via a strict threshold.
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="aws", keywords=tokenize("aws")),)
    )
    jd = parse_job_description("Needs AWS experience", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=1.0, keywords=("aws",)),
        gap_coverage_threshold=1.5,  # impossible threshold -> always "weak"
    )

    result = run_match(dossier, jd, template)

    assert result.weak_categories == ("cloud",)
    assert result.alert_level == AlertLevel.WARNING


def _starter(template_id: str) -> MissionTemplate:
    return load_template(_STARTER_DIR / f"{template_id}.qv-mission.yaml")


def _dossier_from(*bullets: str) -> Dossier:
    return Dossier(
        capabilities=tuple(Capability(domain="D", text=b, keywords=tokenize(b)) for b in bullets)
    )


def test_run_match_variant_spellings_match_starter_template_keywords() -> None:
    """R4: the posting, the dossier and the template meet on one form of each keyword."""
    jd = parse_job_description("Needs CI/CD, SOC 2, ISO 27001, K8s and on-call.", source="test")
    dossier = _dossier_from(
        "Built CI-CD pipelines.",
        "Passed a SOC2 audit and ISO27001 certification.",
        "Ran Kubernetes clusters with an on call rotation.",
    )

    result = run_match(dossier, jd, _starter("devops-senior-mgr"))

    assert result.gaps == ()
    matched = {k for c in result.category_scores for k in c.matched_keywords}
    assert {"cicd", "soc2", "iso27001", "kubernetes", "oncall"} <= matched


def test_run_match_soc_2_no_longer_matches_the_soc_keyword() -> None:
    """R4: "SOC 2" is the compliance report, not a security operations center."""
    jd = parse_job_description("Needs SOC 2 and incident response", source="test")

    result = run_match(_dossier_from("Ran a SOC 2 program"), jd, _starter("cybersec-ops-director"))

    cybersec_incident = next(c for c in result.category_scores if c.name == "incident_response")
    assert "soc" not in cybersec_incident.matched_keywords
    assert "soc" not in cybersec_incident.gap_keywords


def test_run_match_sentence_final_keyword_matches() -> None:
    """R4: a keyword at the end of a dossier bullet still matches the posting."""
    jd = parse_job_description("Needs Terraform experience", source="test")
    template = _template(TemplateCategory(name="cloud", weight=1.0, keywords=("terraform",)))

    result = run_match(_dossier_from("Automated provisioning with Terraform."), jd, template)

    assert result.g_force_score == 100.0


def test_run_match_negated_skill_is_counted_but_warned() -> None:
    """R3: a negated skill still counts toward the score, and the line is flagged.

    Keywords are a bag of tokens, so "no hands-on Kubernetes" matches Kubernetes
    (ADR-0030: the score is unchanged). Still open, backlog item 1: nothing
    removes the line from the score or from the narrative prompt; that would
    take an exclusions section, which was not built.
    """
    dossier = _dossier_from(
        "No hands-on Kubernetes",
        "Never used HashiCorp Vault",
        "Terraform training only",
    )
    jd = parse_job_description("Needs Kubernetes, Terraform and Vault", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=1.0, keywords=("kubernetes", "terraform", "vault"))
    )

    result = run_match(dossier, jd, template)

    assert result.g_force_score == 100.0
    assert result.gaps == ()
    assert [(w.file, w.heading, w.line, w.keywords) for w in result.negation_warnings] == [
        ("Capabilities.md", "D", "No hands-on Kubernetes", ("kubernetes",)),
        ("Capabilities.md", "D", "Never used HashiCorp Vault", ("vault",)),
        ("Capabilities.md", "D", "Terraform training only", ("terraform",)),
    ]


_DEVOPS_ORDER = (
    "cloud_infrastructure",
    "cicd_automation",
    "reliability_operations",
    "leadership",
    "security_compliance",
)


def _posting_shaped(
    asked: tuple[int, int, int, int, int], matched: tuple[int, int, int, int, int]
) -> MatchResult:
    """Run devops-senior-mgr on a synthetic posting asking the first N keywords per category.

    ``asked[i]`` is how many of category i's keywords the posting asks about and
    ``matched[i]`` how many of those the dossier has (the first ones).
    """
    template = _starter("devops-senior-mgr")
    by_name = {c.name: c.keywords for c in template.categories}
    posting_words: list[str] = []
    dossier_bullets: list[str] = []
    for name, n_asked, n_matched in zip(_DEVOPS_ORDER, asked, matched, strict=True):
        posting_words += by_name[name][:n_asked]
        dossier_bullets += [f"Worked with {k}" for k in by_name[name][:n_matched]]
    jd = parse_job_description("Looking for " + " ".join(posting_words), source="test")
    return run_match(_dossier_from(*dossier_bullets), jd, template)


def test_posting_one_shape_keeps_its_score() -> None:
    """R3/R4: 18 of 36 asked across all 5 categories still scores 96.0 (ADR-0033 table)."""
    result = _posting_shaped(asked=(4, 3, 3, 3, 5), matched=(4, 3, 3, 3, 3))

    assert result.asked_template_count == 18
    assert result.asked_category_count == 5
    assert result.g_force_score == result.coverage == 96.0
    assert result.relevance == 50.0
    assert not result.low_relevance


def test_posting_two_shape_skips_security_and_renormalizes() -> None:
    """R3/R4: security not asked is left out: 0.7733 / 0.9 = 85.9 coverage, 41.7% relevance.

    Before ADR-0033 the same posting scored 87.3 (security counted as full).
    """
    result = _posting_shaped(asked=(5, 3, 3, 4, 0), matched=(4, 2, 3, 4, 0))

    security = next(c for c in result.category_scores if c.name == "security_compliance")
    assert not security.asked
    assert result.asked_template_count == 15
    assert result.asked_category_count == 4
    assert result.coverage == 85.9
    assert result.relevance == 41.7
    assert result.relevance_text() == "15 of 36 template keywords (42%)"
    assert not result.low_relevance
    assert result.alert_level == AlertLevel.WARNING  # gaps remain


def test_posting_three_shape_is_low_relevance_not_a_clean_success() -> None:
    """R3/R4: 2 keywords asked, both leadership, both matched: no 100% SUCCESS any more.

    Before ADR-0033 this scored 100.0 SUCCESS.
    """
    result = _posting_shaped(asked=(0, 0, 0, 2, 0), matched=(0, 0, 0, 2, 0))

    assert result.alert_level == AlertLevel.LOW_RELEVANCE
    assert result.low_relevance
    assert (result.asked_template_count, result.asked_category_count) == (2, 1)
    assert result.relevance == 5.6
    # what a person reads: no coverage percentage, though `coverage` stays in the data
    assert result.coverage == 100.0
    assert result.coverage_text() == "not scored (low relevance)"
    assert "%" not in result.coverage_text()
    assert {result.category_coverage_text(c) for c in result.category_scores} == {"-"}
    assert "little of this template" in result.relevance_note()
    assert "Try another template" in result.relevance_note()


def _numbered_template() -> MissionTemplate:
    """Two categories, 3 + 4 distinct keywords (k3 is listed in both), 6 distinct overall."""
    return _template(
        TemplateCategory(name="a", weight=0.5, keywords=("k1", "k2", "k3")),
        TemplateCategory(name="b", weight=0.5, keywords=("k3", "k4", "k5", "k6")),
    )


def _run(template: MissionTemplate, posting: str, dossier: str = "") -> MatchResult:
    bullets = (dossier,) if dossier else ()
    return run_match(_dossier_from(*bullets), parse_job_description(posting, source="t"), template)


def test_exactly_five_keywords_and_two_categories_is_not_low() -> None:
    """R3: the minimums are inclusive: 5 keywords in 2 categories is enough."""
    result = _run(_numbered_template(), "k1 k2 k3 k4 k5", "k1 k2 k3 k4 k5")

    assert (result.asked_template_count, result.asked_category_count) == (5, 2)
    assert not result.low_relevance
    assert result.alert_level == AlertLevel.SUCCESS


def test_four_keywords_is_low_relevance() -> None:
    """R3: one keyword under the minimum, with the template large enough to need 5."""
    result = _run(_numbered_template(), "k1 k2 k4 k5", "k1 k2 k4 k5")

    assert result.asked_template_count == 4
    assert result.alert_level == AlertLevel.LOW_RELEVANCE


def test_one_category_with_many_keywords_is_low_relevance() -> None:
    """R3: 3 keywords all in one category of two: only 1 category asked."""
    template = _template(
        TemplateCategory(name="a", weight=0.5, keywords=("k1", "k2", "k3", "k4", "k5", "k6")),
        TemplateCategory(name="b", weight=0.5, keywords=("z1", "z2")),
    )

    result = _run(template, "k1 k2 k3 k4 k5 k6", "k1 k2 k3 k4 k5 k6")

    assert (result.asked_template_count, result.asked_category_count) == (6, 1)
    assert result.alert_level == AlertLevel.LOW_RELEVANCE


def test_nothing_asked_is_low_relevance_with_no_coverage_number() -> None:
    """R3: zero asked: no coverage number, never 100%, and it says so in plain words."""
    result = _run(_numbered_template(), "Needs welding", "k1 k2")

    assert result.alert_level == AlertLevel.LOW_RELEVANCE
    assert result.coverage is None
    assert result.g_force_score == 0.0
    assert result.coverage_text() == "no template keywords found in this posting"
    assert "no template keywords found" in result.relevance_note().lower()
    assert "100" not in result.coverage_text()
    assert result.to_dict()["coverage"] is None


def test_a_keyword_in_two_categories_counts_once_in_relevance() -> None:
    """R3: k3 is listed twice; asking k1 k2 k3 k4 is 4 distinct of 6, not 5 of 7."""
    result = _run(_numbered_template(), "k1 k2 k3 k4", "k1 k2 k3 k4")

    assert result.template_keyword_count == 6
    assert result.asked_template_count == 4
    assert result.relevance == 66.7
    # counted twice it would reach the 5-keyword minimum and not be low
    assert result.alert_level == AlertLevel.LOW_RELEVANCE


def test_red_flag_with_low_relevance_is_critical() -> None:
    """R3/R4: red flags come first: CRITICAL, though low relevance still shows."""
    template = _template(
        TemplateCategory(name="a", weight=0.5, keywords=("k1", "k2", "k3")),
        TemplateCategory(name="b", weight=0.5, keywords=("k4", "k5", "k6")),
        red_flag_phrases=("wear many hats",),
    )

    result = _run(template, "k1 and we wear many hats", "k1")

    assert result.red_flags
    assert result.low_relevance
    assert result.alert_level == AlertLevel.CRITICAL
    assert "little of this template" in result.relevance_note()


def test_one_category_template_that_asks_everything_is_not_low() -> None:
    """R3: the minimum categories is capped by the template's size (ADR-0033)."""
    template = _template(TemplateCategory(name="only", weight=1.0, keywords=("k1", "k2", "k3")))

    result = _run(template, "k1 k2 k3", "k1 k2 k3")

    assert result.asked_category_count == 1
    assert not result.low_relevance
    assert result.alert_level == AlertLevel.SUCCESS


def test_four_keyword_template_that_asks_everything_is_not_low() -> None:
    """R3: the minimum keywords is capped by the template's keyword count (ADR-0033)."""
    template = _template(
        TemplateCategory(name="a", weight=0.5, keywords=("k1", "k2")),
        TemplateCategory(name="b", weight=0.5, keywords=("k3", "k4")),
    )

    result = _run(template, "k1 k2 k3 k4", "k1 k2 k3 k4")

    assert (result.asked_template_count, result.template_keyword_count) == (4, 4)
    assert not result.low_relevance
    assert result.alert_level == AlertLevel.SUCCESS


def test_score_below_forty_is_still_critical_when_relevance_is_enough() -> None:
    """R4: the score band stays, after low relevance in the order."""
    result = _run(_numbered_template(), "k1 k2 k3 k4 k5 k6", "k1")

    assert not result.low_relevance
    assert result.coverage is not None and result.coverage < 40.0
    assert result.alert_level == AlertLevel.CRITICAL


def test_run_match_counts_are_asked_keywords_per_category_and_overall() -> None:
    """R3: "N of M asked" per category; overall counts a shared keyword once."""
    jd = parse_job_description("Needs AWS, Terraform and Kubernetes", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=0.5, keywords=("aws", "terraform", "kubernetes")),
        TemplateCategory(name="iac", weight=0.5, keywords=("terraform", "ansible")),
        TemplateCategory(name="people", weight=0.0, keywords=("mentoring",)),
    )

    result = run_match(_dossier_from("AWS and Terraform"), jd, template)

    cloud, iac, people = result.category_scores
    assert cloud.counts_text() == "2 of 3 asked"
    assert iac.counts_text() == "1 of 1 asked"
    assert people.counts_text() == "not asked (left out of the score)"
    assert (people.matched_count, people.asked_count, people.coverage) == (0, 0, 1.0)
    assert not people.asked
    # terraform sits in two categories but counts once overall
    assert (result.matched_count, result.asked_count) == (2, 3)
    assert result.counts_text() == "2 of 3 template keywords in this posting are in your dossier"


def test_run_match_counts_when_nothing_is_asked() -> None:
    """R3: a posting that asks nothing of the template says so (ADR-0033: no number, not 100)."""
    jd = parse_job_description("Needs welding", source="test")
    template = _template(TemplateCategory(name="cloud", weight=1.0, keywords=("aws",)))

    result = run_match(_dossier_from("AWS"), jd, template)

    assert result.asked_count == 0
    assert result.counts_text() == "No template keywords found in this posting"
    assert result.coverage is None
    assert result.alert_level == AlertLevel.LOW_RELEVANCE


def test_run_match_category_without_keywords_counts_every_posting_keyword() -> None:
    """R3: a category with no keywords asks about every posting keyword, and M says so."""
    jd = parse_job_description("AWS and welding", source="test")
    template = _template(TemplateCategory(name="anything", weight=1.0))

    result = run_match(_dossier_from("AWS"), jd, template)

    assert (result.category_scores[0].matched_count, result.category_scores[0].asked_count) == (
        1,
        2,
    )
    assert result.g_force_score == 50.0


def test_run_match_counts_do_not_change_score_or_alert_level() -> None:
    """R4: the scoring rules stay as they are; counts and warnings are display only."""
    jd = parse_job_description("Needs Kubernetes and Terraform", source="test")
    template = _template(
        TemplateCategory(name="cloud", weight=1.0, keywords=("kubernetes", "terraform"))
    )

    plain = run_match(_dossier_from("Kubernetes and Terraform"), jd, template)
    negated = run_match(_dossier_from("No Kubernetes", "Terraform"), jd, template)

    assert plain.g_force_score == negated.g_force_score == 100.0
    assert plain.alert_level == negated.alert_level == AlertLevel.SUCCESS
    assert plain.negation_warnings == ()
    assert len(negated.negation_warnings) == 1
