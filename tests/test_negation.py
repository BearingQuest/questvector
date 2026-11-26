"""Unit tests for questvector.core.negation (ADR-0030)."""

from __future__ import annotations

import pytest

from questvector.core.markdown_parser import tokenize
from questvector.core.models import Capability, ChronologyEntry, Dossier, ImpactStatement
from questvector.core.negation import _flagged_keywords, find_negation_warnings

_MATCHED = frozenset({"kubernetes", "terraform", "vault", "node.js", "python"})


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("No hands-on Kubernetes", ("kubernetes",)),
        ("Never used HashiCorp Vault", ("vault",)),
        ("Terraform training only", ("terraform",)),
        ("No hands-on K8s", ("kubernetes",)),
        ("Terraform (training only)", ("terraform",)),
        ("No production experience with Kubernetes", ("kubernetes",)),
        ("Without Terraform or Vault", ("terraform", "vault")),
        ("No hands-on node.js", ("node.js",)),
    ],
)
def test_negation_true_positives(line: str, expected: tuple[str, ...]) -> None:
    """R3: a cue next to a matched keyword flags the line."""
    assert _flagged_keywords(line, _MATCHED) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Led Kubernetes and Terraform migrations",
        "Not only Kubernetes but also Terraform",
        "Not just Vault, also Terraform",
        "No Java but strong Terraform",
        "Built node.js services, no downtime",
        "No hands-on Ansible",  # the cue is next to a keyword that did not match
    ],
)
def test_negation_lines_that_must_not_warn(line: str) -> None:
    """R3: no warning without a cue next to a matched keyword, or when the rule excludes it."""
    assert _flagged_keywords(line, _MATCHED) == ()


def test_negation_cue_in_a_different_bullet_does_not_warn() -> None:
    """R3: a cue is checked within one line, never across bullets."""
    dossier = Dossier(
        capabilities=(
            Capability(domain="Cloud", text="No hands-on Ansible", keywords=tokenize("ansible")),
            Capability(domain="Cloud", text="Kubernetes", keywords=tokenize("Kubernetes")),
        )
    )

    assert find_negation_warnings(dossier, _MATCHED) == ()


def test_negation_accepted_false_positive_is_pinned() -> None:
    """R3: accepted false positive (ADR-0030): "no" near a keyword in a non-skill sentence."""
    line = "No downtime during the Kubernetes migration"
    assert _flagged_keywords(line, _MATCHED) == ("kubernetes",)


def test_negation_accepted_false_positive_keyword_claimed_elsewhere() -> None:
    """R3: accepted false positive (ADR-0030): a line is flagged even if another line claims it."""
    dossier = Dossier(
        capabilities=(
            Capability(domain="Cloud", text="No hands-on Kubernetes"),
            Capability(domain="Cloud", text="Ran Kubernetes clusters"),
        )
    )

    warnings = find_negation_warnings(dossier, _MATCHED)

    assert [w.line for w in warnings] == ["No hands-on Kubernetes"]


@pytest.mark.parametrize(
    "line",
    [
        "I don't have Kubernetes",
        "I don\u2019t have Kubernetes",
        "Haven't used Terraform",
        "Haven\u2019t used Terraform",
    ],
)
def test_negation_contractions_are_not_handled(line: str) -> None:
    """R3: not handled (ADR-0030): contractions, with a straight or a curly apostrophe."""
    assert _flagged_keywords(line, _MATCHED) == ()


@pytest.mark.parametrize(
    "line",
    [
        "Kubernetes: none",  # a trailing "none" is not a cue
        "No A B C D Kubernetes",  # the cue is more than four tokens before the keyword
        "No. 1 ranked Kubernetes team",  # "No." ends a clause, so the cue never reaches it
    ],
)
def test_negation_other_cases_not_handled(line: str) -> None:
    """R3: not handled (ADR-0030): a trailing "none", a distant cue, and "No." as a clause end."""
    assert _flagged_keywords(line, _MATCHED) == ()


def test_negation_checks_each_dossier_part_and_names_file_and_heading() -> None:
    """R3: Capabilities, Chronology headings and bullets, and Impact bullets are checked."""
    dossier = Dossier(
        capabilities=(Capability(domain="Cloud", text="No hands-on Kubernetes"),),
        chronology=(
            ChronologyEntry(heading="Acme - No Terraform Lead", bullets=("Never used Vault",)),
        ),
        impact=(ImpactStatement(heading="Savings", bullets=("Without Python scripts",)),),
    )

    warnings = find_negation_warnings(dossier, _MATCHED)

    assert [(w.file, w.heading, w.line, w.keywords) for w in warnings] == [
        ("Capabilities.md", "Cloud", "No hands-on Kubernetes", ("kubernetes",)),
        ("Chronology.md", "Acme - No Terraform Lead", "Acme - No Terraform Lead", ("terraform",)),
        ("Chronology.md", "Acme - No Terraform Lead", "Never used Vault", ("vault",)),
        ("Impact.md", "Savings", "Without Python scripts", ("python",)),
    ]


def test_negation_does_not_check_capabilities_or_impact_headings() -> None:
    """R3: those headings are labels, not claims (ADR-0027), so a cue in one is not flagged."""
    dossier = Dossier(
        capabilities=(Capability(domain="No Kubernetes Here", text="Python"),),
        impact=(ImpactStatement(heading="Never Terraform", bullets=("Saved money",)),),
    )

    assert find_negation_warnings(dossier, _MATCHED) == ()
