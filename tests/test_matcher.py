"""Unit tests for questvector.core.matcher."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

import questvector
from questvector.core.markdown_parser import tokenize
from questvector.core.matcher import parse_job_description, run_match
from questvector.core.models import (
    AlertLevel,
    Capability,
    Dossier,
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


def test_run_match_category_with_no_relevant_keywords_scores_as_fully_covered() -> None:
    dossier = Dossier()
    jd = parse_job_description("A job description with no overlapping terms at all", source="test")
    # Category keywords that don't appear in the JD at all -> nothing "relevant" to check.
    template = _template(
        TemplateCategory(name="niche", weight=1.0, keywords=("cobol", "mainframe"))
    )

    result = run_match(dossier, jd, template)

    assert result.g_force_score == 100.0


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


def test_run_match_large_dossier_saturates_score_known_limitation() -> None:
    """R4: known limitation, backlog item 1: a large dossier scores 100.0 on any posting.

    A keyword counts if it appears anywhere in the dossier, so a dossier that
    holds the template's vocabulary covers an on-target and an off-target
    posting equally. The scores are unchanged (ADR-0030); the asked counts now
    tell the postings apart. Still open: the formula. A deliberate formula change
    (a new ADR superseding ADR-0006) updates this test.
    """
    template = _starter("devops-senior-mgr")
    vocabulary = sorted({k for c in template.categories for k in c.keywords})
    bullets = [f"Led {a} and {b} work for the team" for a, b in pairwise(vocabulary)]
    bullets += [f"Delivered project {i} with automation" for i in range(120 - len(bullets))]
    dossier = _dossier_from(*bullets)
    on_target = parse_job_description(
        "Senior DevOps Manager: AWS, Terraform, Kubernetes, Jenkins, monitoring, incident, "
        "mentoring, hiring, budget, compliance, vulnerability.",
        source="test",
    )
    off_target = parse_job_description(
        "Analyst: compliance, hardening, iam, sla, uptime, budget, cloudformation.", source="test"
    )

    assert len(bullets) >= 100
    on_result = run_match(dossier, on_target, template)
    off_result = run_match(dossier, off_target, template)
    assert on_result.g_force_score == 100.0
    assert off_result.g_force_score == 100.0
    assert (on_result.matched_count, on_result.asked_count) == (12, 12)
    assert (off_result.matched_count, off_result.asked_count) == (7, 7)
    # The finding for the later formula decision: a category the posting never
    # asks about still counts as full coverage at its full weight.
    cicd = next(c for c in off_result.category_scores if c.name == "cicd_automation")
    assert (cicd.asked_count, cicd.coverage, cicd.weight) == (0, 1.0, 0.2)
    assert cicd.counts_text() == "not asked (counts as full coverage)"


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
    assert people.counts_text() == "not asked (counts as full coverage)"
    assert (people.matched_count, people.asked_count, people.coverage) == (0, 0, 1.0)
    # terraform sits in two categories but counts once overall
    assert (result.matched_count, result.asked_count) == (2, 3)
    assert result.counts_text() == "2 of 3 template keywords in this posting are in your dossier"


def test_run_match_counts_when_nothing_is_asked() -> None:
    """R3: a posting that asks nothing of the template says so, and the score is unchanged."""
    jd = parse_job_description("Needs welding", source="test")
    template = _template(TemplateCategory(name="cloud", weight=1.0, keywords=("aws",)))

    result = run_match(_dossier_from("AWS"), jd, template)

    assert result.asked_count == 0
    assert result.counts_text() == "No template keywords found in this posting"
    assert result.g_force_score == 100.0


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
