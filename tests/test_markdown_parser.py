"""Unit tests for questvector.core.markdown_parser."""

# ruff: noqa: RUF001, RUF002
# The en and em dashes are part of the role heading form under test.
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from questvector.core.markdown_parser import (
    parse_capabilities,
    parse_chronology,
    parse_dossier,
    parse_impact,
    parse_role_heading,
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


def test_role_heading_parses_title_employer_and_month_dates() -> None:
    """R9: "Title — Employer (Mon YYYY – Mon YYYY)" gives title, employer and month dates."""
    role = parse_role_heading(
        "Engineering Manager, Platform — Larkspur Freight (Mar 2021 – Feb 2025)"
    )

    assert role.title == "Engineering Manager, Platform"
    assert role.employer == "Larkspur Freight"
    assert role.start == date(2021, 3, 1)
    assert role.end == date(2025, 2, 1)


@pytest.mark.parametrize(
    "heading",
    [
        "Senior SRE — Acme (jan 2020 - present)",
        "Senior SRE — Acme (JAN 2020–PRESENT)",
        "Senior SRE — Acme (Jan 2020 – Present)",
    ],
)
def test_role_heading_accepts_present_hyphen_and_any_month_case(heading: str) -> None:
    """R9: "Present" ends a role; a hyphen or en dash separates dates; month case is free."""
    role = parse_role_heading(heading)

    assert role.end is None
    assert role.start == date(2020, 1, 1)


@pytest.mark.parametrize(
    ("heading", "reason"),
    [
        ("Acme Corp — Senior SRE (2020-2023)", "does not match"),
        ("Senior SRE at Acme (Jan 2020 – Mar 2023)", "does not match"),
        ("Senior SRE — Acme", "does not match"),
        ("Senior SRE — Acme (Sept 2020 – Mar 2023)", '"Sept" is not a three-letter month'),
        ("Senior SRE — Acme (Jan 2020 – Foo 2023)", '"Foo" is not a three-letter month'),
        ("Senior SRE — Acme (Mar 2023 – Jan 2020)", "end date is before the start date"),
    ],
)
def test_role_heading_errors_say_what_is_wrong(heading: str, reason: str) -> None:
    """R9: a heading that doesn't fit the form raises a ParseError saying why."""
    with pytest.raises(ParseError, match=reason):
        parse_role_heading(heading)


def test_resume_parse_names_every_heading_that_does_not_fit(tmp_path: Path) -> None:
    """R9: with require_roles, one error names the file, each bad heading and the form."""
    (tmp_path / "Chronology.md").write_text(
        "## Senior SRE — Acme (Jan 2020 – Mar 2023)\n- ok\n"
        "## Acme Corp — SRE (2016-2019)\n- old form\n"
        "## Intern — Foo (Sept 2010 – Dec 2010)\n- bad month\n",
        encoding="utf-8",
    )

    with pytest.raises(ParseError) as exc_info:
        parse_dossier(tmp_path, require_roles=True)

    message = str(exc_info.value)
    assert "Chronology.md" in message
    assert '"Acme Corp — SRE (2016-2019)"' in message
    assert '"Intern — Foo (Sept 2010 – Dec 2010)"' in message
    assert '"Senior SRE — Acme (Jan 2020 – Mar 2023)"' not in message.split("don't fit:")[1]
    assert "Title — Employer (Mon YYYY – Mon YYYY or Present)" in message


def test_report_style_still_accepts_any_heading(tmp_path: Path) -> None:
    """R9: without require_roles every heading parses, with role None where it doesn't fit."""
    (tmp_path / "Chronology.md").write_text(
        "## Acme Corp — Senior SRE (2020-2023)\n- a\n"
        "## Senior SRE — Acme (Jan 2020 – Present)\n- b\n",
        encoding="utf-8",
    )

    entries = parse_dossier(tmp_path).chronology

    assert [e.role is None for e in entries] == [True, False]


def test_month_names_in_a_role_heading_are_not_keywords(tmp_path: Path) -> None:
    """R9: a parsed role contributes its title and employer words, never "mar" or "present"."""
    (tmp_path / "Chronology.md").write_text(
        "## Senior SRE — Acme (Mar 2020 – Present)\n- Ran Kubernetes\n", encoding="utf-8"
    )

    (entry,) = parse_dossier(tmp_path).chronology

    assert {"senior", "sre", "acme", "kubernetes"} <= entry.keywords
    assert not {"mar", "present"} & entry.keywords


def test_the_launch_stub_uses_the_role_heading_form(tmp_path: Path) -> None:
    """R9: a new workspace's Chronology stub already parses in the role form."""
    from questvector.core import workspace

    workspace.init_workspace(tmp_path / "ws")

    (entry,) = parse_dossier(tmp_path / "ws", require_roles=True).chronology
    assert entry.role is not None
