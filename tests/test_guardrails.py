"""Tests for questvector.core.guardrails: the output check on generated summaries (R14).

All text is synthetic. The traps come from tests/fixtures/live_narrative/answer_key.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from questvector.core import llm
from questvector.core.guardrails import check_narrative, strip_extras
from questvector.core.markdown_parser import parse_dossier

FIXTURES = Path(__file__).parent / "fixtures" / "live_narrative"
ANSWER_KEY = json.loads((FIXTURES / "answer_key.json").read_text(encoding="utf-8"))
SENT = llm.dossier_context_for_prompt(parse_dossier(FIXTURES))

CLEAN = (
    "I ran AWS production environments with Terraform and Kubernetes, cut annual AWS spend "
    "by 31%, and containerized 40 legacy services with Docker."
)
NOTE_5_NOV = (
    "*Note: I did not claim Datadog, HashiCorp Vault or SOC 2 experience, because the "
    "dossier excerpts don't mention them.*"
)


def kinds(text: str, sent: str = SENT) -> list[str]:
    return [flag.kind for flag in check_narrative(text, sent).flags]


# --- strip -----------------------------------------------------------------


def test_clean_summary_is_unchanged_and_unflagged() -> None:
    """R14: a clean summary passes through untouched with nothing removed or flagged."""
    result = check_narrative(CLEAN, SENT)

    assert result.text == CLEAN
    assert result.removed == ()
    assert result.flags == ()


def test_the_5_nov_shape_strips_the_italic_note_naming_the_trap_keywords() -> None:
    """R14: a summary followed by an italic note listing trap keywords keeps only the summary."""
    result = check_narrative(f"{CLEAN}\n\n{NOTE_5_NOV}", SENT)

    assert result.text == CLEAN
    for trap in ANSWER_KEY["trap_keywords"]:
        assert trap not in result.text
        assert trap in " ".join(result.removed)
    assert result.report_lines()[0].startswith("Removed from the summary (not exported):")


@pytest.mark.parametrize(
    "tail",
    [
        "\n---\nA note about what I left out.",
        "\n\n***\n\nAnother paragraph.",
        "\n\nA second paragraph that explains the first.",
        "\n*I did not claim Datadog.*",
        "\n[Note: no Datadog was mentioned.]",
        "\n(I left out HashiCorp Vault.)",
        "\nNote: SOC 2 was not in the excerpts.",
        "\n**Note:** SOC 2 was not in the excerpts.",
    ],
)
def test_anything_after_the_summary_paragraph_is_stripped(tail: str) -> None:
    """R14: a second paragraph, rule, italic, bracketed or Note: line after the summary goes."""
    result = check_narrative(CLEAN + tail, SENT)

    assert result.text == CLEAN
    assert result.removed


@pytest.mark.parametrize(
    "head", ["## Summary\n\n", "# Resume Summary\n", "Here is a summary tailored to the role:\n\n"]
)
def test_a_heading_or_preamble_before_the_summary_is_stripped(head: str) -> None:
    """R14: a heading or "Here is ..." line before the summary is removed and reported."""
    result = check_narrative(head + CLEAN, SENT)

    assert result.text == CLEAN
    assert len(result.removed) == 1


def test_a_multi_line_summary_paragraph_is_kept_whole() -> None:
    """R14: line breaks inside the one paragraph don't cut it short."""
    wrapped = "I ran AWS production environments\nwith Terraform and Kubernetes."

    assert check_narrative(wrapped, SENT).text == (
        "I ran AWS production environments with Terraform and Kubernetes."
    )


def test_output_with_no_recognizable_summary_is_returned_as_is() -> None:
    """R14: if stripping would leave nothing, the text is kept (and checked), not emptied."""
    text, removed = strip_extras("## Only a heading")

    assert text == "## Only a heading"
    assert removed == ()


# --- numbers and terms -----------------------------------------------------


def test_a_number_not_in_the_sent_text_is_flagged() -> None:
    """R14: "7+ years" comes from the job description, not the dossier, so it is flagged."""
    flags = check_narrative("I bring 7+ years of platform experience with AWS.", SENT).flags

    assert [f.kind for f in flags] == ["unsupported_number"]
    assert flags[0].terms == ("7+",)


def test_numbers_in_the_sent_text_are_not_flagged() -> None:
    """R14: the answer key's allowed numbers that Capabilities.md states are not flagged."""
    present = ["31%", "40", "15"]
    assert set(present) <= set(ANSWER_KEY["allowed_numbers"])
    assert all(n in SENT for n in present)
    for number in present:
        assert kinds(f"I delivered a result of {number} on AWS.") == [], number


def test_every_trap_keyword_is_flagged_when_the_dossier_text_lacks_it() -> None:
    """R14: Datadog, HashiCorp Vault and SOC 2 are flagged as terms not in the sent text."""
    for name in ANSWER_KEY["trap_keywords"]:
        assert "unsupported_term" in kinds(f"I also ran {name} for the platform."), name


def test_every_invented_term_is_flagged() -> None:
    """R14: each invented_terms entry in the answer key is flagged when named in a summary."""
    for term in ANSWER_KEY["invented_terms"]:
        assert "unsupported_term" in kinds(f"I also ran {term.title()} for the team."), term


def test_terms_in_the_sent_text_are_not_flagged_even_in_variant_forms() -> None:
    """R14: AWS, Terraform, Kubernetes, EKS and K8s all appear in the sent text (ADR-0027)."""
    assert kinds("I ran AWS with Terraform on Kubernetes (EKS), also called K8s.") == []


def test_normalized_phrases_match_their_canonical_form() -> None:
    """R14: "SOC 2" and "ISO 27001" count as present when the sent text writes them differently."""
    sent = "Passed a SOC2 audit and held ISO/IEC 27001:2022 certification"

    assert kinds("I passed a SOC 2 audit and kept ISO 27001 current.", sent) == []


def test_flags_never_change_the_returned_text() -> None:
    """R14: flag, don't block: a flagged summary is returned in full."""
    text = "I used Datadog for 7 years."
    result = check_narrative(text, SENT)

    assert result.text == text
    assert {f.kind for f in result.flags} == {"unsupported_number", "unsupported_term"}


def test_accepted_miss_a_sentence_initial_plain_word_is_not_checked() -> None:
    """R14 (accepted limit, ADR-0032): a sentence-initial plain word isn't checked."""
    assert kinds("Datadog dashboards were my main tool.") == []


def test_accepted_miss_spelled_out_numbers_are_not_checked() -> None:
    """R14 (accepted limit, ADR-0032): "seven years" isn't a numeric token, so it isn't flagged."""
    assert kinds("I led teams for seven years on AWS.") == []


def test_accepted_false_positive_the_target_employer_is_flagged() -> None:
    """R14 (accepted, ADR-0032): naming the employer from the posting is flagged for review."""
    assert "unsupported_term" in kinds("I want to bring my AWS skills to Quillon Systems.")


# --- pronouns and depth words ---------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "He ran AWS production environments.",
        "She led the platform team.",
        "I mentored him and his team on AWS.",
        "The candidate ran AWS in three regions.",
        "I thanked her for the help on AWS.",
    ],
)
def test_third_person_pronouns_are_flagged(sentence: str) -> None:
    """R14: he, she, his, her, him, himself, herself and "the candidate" are flagged."""
    assert "third_person" in kinds(sentence)


def test_they_is_flagged_only_when_the_sentence_has_no_first_person_word() -> None:
    """R14: "they" about the candidate is flagged; "they" about a team after "I" is not."""
    assert "third_person" in kinds("They ran AWS production environments.")
    assert "third_person" not in kinds("I coached the leads so they could run AWS alone.")


@pytest.mark.parametrize(
    "sentence",
    [
        "I have hands-on Kubernetes experience.",
        "I am an expert in Terraform.",
        "I have deep AWS knowledge.",
        "I bring extensive Docker experience.",
    ],
)
def test_depth_words_the_dossier_does_not_use_are_flagged(sentence: str) -> None:
    """R14: "hands-on", "expert", "deep" and "extensive" are flagged when the dossier lacks them."""
    assert "depth_claim" in kinds(sentence)


def test_a_depth_word_the_dossier_itself_uses_is_not_flagged() -> None:
    """R14: the same depth word in the sent text is a claim the dossier makes."""
    sent = "Hands-on Kubernetes operations across three regions"

    assert "depth_claim" not in kinds("I have hands on Kubernetes operations.", sent)


# --- prompt and context ----------------------------------------------------


def test_prompt_forbids_extras_and_invented_facts() -> None:
    """R14: the system prompt asks for the paragraph only and bans invented facts."""
    prompt = llm._NARRATIVE_SYSTEM_PROMPT.lower()

    for phrase in (
        "first person",
        "paragraph only",
        "nothing after the paragraph",
        "only facts stated in the dossier excerpts",
        "titles, metrics, numbers, dates, durations, employers or technologies",
        "hands-on, expert or deep",
        "not a source of facts about the candidate",
    ):
        assert phrase in prompt, phrase
    assert "summary paragraph only" in llm.build_narrative_prompt("a", "b")


def test_dossier_context_is_the_first_20_capability_bullets_only() -> None:
    """R14: the checked text is exactly what is sent: 20 capability bullets, no chronology."""
    dossier = parse_dossier(FIXTURES)
    context = llm.dossier_context_for_prompt(dossier)

    assert context.splitlines() == [c.text for c in dossier.capabilities[:20]]
    assert "Larkspur" not in context
    assert "Tidewell" not in context
