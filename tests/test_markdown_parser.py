"""Unit tests for questvector.core.markdown_parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from questvector.core.markdown_parser import (
    parse_capabilities,
    parse_chronology,
    parse_dossier,
    parse_impact,
    tokenize,
)
from questvector.exceptions import ParseError


def test_tokenize_lowercases_and_strips_stopwords() -> None:
    tokens = tokenize("The Senior AWS Engineer is a great fit for the team")
    assert "the" not in tokens
    assert "is" not in tokens
    assert "a" not in tokens
    assert "aws" in tokens
    assert "engineer" in tokens
    assert "senior" in tokens


def test_tokenize_empty_string_returns_empty_set() -> None:
    assert tokenize("") == frozenset()


def test_parse_capabilities_groups_bullets_under_domain(
    tmp_path: Path, sample_capabilities_md: str
) -> None:
    """R2: the dossier parser groups bullets under their headings."""
    path = tmp_path / "Capabilities.md"
    path.write_text(sample_capabilities_md, encoding="utf-8")

    capabilities = parse_capabilities(path)

    assert len(capabilities) == 4
    assert capabilities[0].domain == "Cloud Infrastructure"
    assert "aws" in capabilities[0].keywords
    assert capabilities[2].domain == "Leadership"


def test_parse_capabilities_missing_file_raises_parse_error(tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        parse_capabilities(tmp_path / "does-not-exist.md")


def test_parse_capabilities_empty_file_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "Capabilities.md"
    path.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(ParseError):
        parse_capabilities(path)


def test_parse_capabilities_no_headings_or_bullets_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "Capabilities.md"
    path.write_text("Just some prose with no structure at all.", encoding="utf-8")
    with pytest.raises(ParseError):
        parse_capabilities(path)


def test_parse_capabilities_bad_encoding_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "Capabilities.md"
    path.write_bytes(b"## Domain\n- \xff\xfe invalid utf-8 bytes\n")
    with pytest.raises(ParseError):
        parse_capabilities(path)


def test_parse_capabilities_orphan_bullets_before_heading_are_uncategorized(tmp_path: Path) -> None:
    path = tmp_path / "Capabilities.md"
    path.write_text("- an orphan bullet\n\n## Real Domain\n- a real bullet\n", encoding="utf-8")

    capabilities = parse_capabilities(path)

    assert capabilities[0].domain == "Uncategorized"
    assert capabilities[1].domain == "Real Domain"


def test_parse_chronology_groups_bullets_by_role(tmp_path: Path, sample_chronology_md: str) -> None:
    path = tmp_path / "Chronology.md"
    path.write_text(sample_chronology_md, encoding="utf-8")

    entries = parse_chronology(path)

    assert len(entries) == 1
    assert entries[0].heading == "Acme Corp — Senior SRE (2020-2023)"
    assert len(entries[0].bullets) == 2
    assert "aws" in entries[0].keywords


def test_parse_impact_groups_bullets_by_heading(tmp_path: Path, sample_impact_md: str) -> None:
    path = tmp_path / "Impact.md"
    path.write_text(sample_impact_md, encoding="utf-8")

    statements = parse_impact(path)

    assert len(statements) == 1
    assert statements[0].heading == "Cost Optimization"


def test_parse_dossier_tolerates_missing_files(tmp_path: Path, sample_capabilities_md: str) -> None:
    (tmp_path / "Capabilities.md").write_text(sample_capabilities_md, encoding="utf-8")
    # Chronology.md and Impact.md intentionally absent.

    dossier = parse_dossier(tmp_path)

    assert len(dossier.capabilities) == 4
    assert dossier.chronology == ()
    assert dossier.impact == ()


def test_parse_dossier_raises_if_present_file_is_malformed(
    tmp_path: Path, sample_capabilities_md: str
) -> None:
    (tmp_path / "Capabilities.md").write_text(sample_capabilities_md, encoding="utf-8")
    (tmp_path / "Chronology.md").write_text("", encoding="utf-8")

    with pytest.raises(ParseError):
        parse_dossier(tmp_path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CI/CD", "cicd"),
        ("CI-CD", "cicd"),
        ("CICD", "cicd"),
        ("CI CD", "cicd"),
        ("SOC 2", "soc2"),
        ("SOC-2", "soc2"),
        ("SOC2", "soc2"),
        ("ISO 27001", "iso27001"),
        ("ISO/IEC 27001:2022", "iso27001"),
        ("ISO27001", "iso27001"),
        ("K8s", "kubernetes"),
        ("Kubernetes", "kubernetes"),
        ("on-call", "oncall"),
        ("on call", "oncall"),
        ("TCP/IP", "tcpip"),
        ("cloud-native", "cloudnative"),
        ("Cloud Native", "cloudnative"),
        ("PCI-DSS", "pci"),
        ("Infrastructure as Code", "iac"),
    ],
)
def test_tokenize_maps_common_variants_to_one_form(text: str, expected: str) -> None:
    """R2: common spellings of one term normalize to the same keyword."""
    assert tokenize(text) == frozenset({expected})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SOC 20", {"soc"}),
        ("k8sx", {"k8sx"}),
        ("specific CD", {"specific", "cd"}),
        ("socket 2", {"socket"}),
        ("iso 270010", {"iso"}),
    ],
)
def test_tokenize_phrase_rules_do_not_fire_inside_other_words(
    text: str, expected: set[str]
) -> None:
    """R2: a phrase rule only fires on whole words, never inside another word."""
    assert tokenize(text) == frozenset(expected)


def test_tokenize_on_call_in_ordinary_prose_becomes_oncall() -> None:
    """R2: accepted false positive (ADR-0027): "on call" in prose is read as oncall."""
    assert "oncall" in tokenize("The team relies on call logs")


def test_tokenize_drops_trailing_punctuation_from_the_last_word() -> None:
    """R2: a keyword at the end of a sentence matches the same keyword mid-sentence."""
    assert tokenize("Needs AWS and Kubernetes.") == frozenset({"needs", "aws", "kubernetes"})
    assert tokenize("Terraform, AWS.") == frozenset({"terraform", "aws"})


def test_tokenize_keeps_internal_and_meaningful_punctuation() -> None:
    """R2: c++, c# and node.js are not damaged by trailing-punctuation stripping."""
    assert tokenize("C++, C# and Node.js.") == frozenset({"c++", "c#", "node.js"})


def test_parse_chronology_counts_role_title_words_in_heading(tmp_path: Path) -> None:
    """R2: a role title in a Chronology heading counts as a keyword."""
    path = tmp_path / "Chronology.md"
    path.write_text(
        "## Acme - Engineering Manager (2020-2023)\n- Led a team and ran on-call\n",
        encoding="utf-8",
    )

    entries = parse_chronology(path)

    assert "manager" in entries[0].keywords
    assert "engineering" in entries[0].keywords
    assert entries[0].heading == "Acme - Engineering Manager (2020-2023)"


def test_parse_capabilities_and_impact_headings_do_not_count(tmp_path: Path) -> None:
    """R2: Capabilities and Impact headings are labels, not claims, so they don't count."""
    capabilities_path = tmp_path / "Capabilities.md"
    capabilities_path.write_text("## Leadership\n- Ran a budget\n", encoding="utf-8")
    impact_path = tmp_path / "Impact.md"
    impact_path.write_text("## Cost Optimization\n- Cut monthly spend\n", encoding="utf-8")

    capability = parse_capabilities(capabilities_path)[0]
    statement = parse_impact(impact_path)[0]

    assert "leadership" not in capability.keywords
    assert "optimization" not in statement.keywords
