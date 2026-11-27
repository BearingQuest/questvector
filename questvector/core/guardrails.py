"""Output check for AI-generated summaries (PRD R14, ADR-0032).

A summary is untrusted text. Before it is shown or exported, :func:`check_narrative`
does two separate things:

* **Strip** everything that isn't the one summary paragraph: a heading or "Here is
  ..." line before it, and a second paragraph, horizontal rule, italic or bracketed
  note, or "Note:" line after it. What was removed is reported, never dropped silently.
* **Flag** sentences the user should review: a number, a capitalized name or technology
  term, or a depth word ("hands-on", "expert") that isn't in the dossier text that was
  sent to the model, and third-person pronouns. Flags never block an export and never
  go into the exported file.

"Appears in the dossier text" means the sent text, not the job description. Terms are
compared the ADR-0027 way (:mod:`questvector.core.normalize`), so "K8s", "CI/CD" and
"SOC 2" meet their canonical forms. The false positives and misses this accepts are
listed in ADR-0032 and pinned by ``tests/test_guardrails.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from questvector.core.normalize import normalize_text, normalized_tokens

_RULE_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
_WRAPPED_NOTE_RE = re.compile(r"^\s*(?:\*[^*].*\*|_[^_].*_|\[.*\]|\(.*\))\s*$")
_NOTE_RE = re.compile(r"^\s*(?:\*+|_+)?\s*(?:note|notes|disclaimer)\b\s*(?:\*+|_+)?\s*[:\-]", re.I)
_PREAMBLE_RE = re.compile(r"^\s*(?:here(?:'s| is| are)|sure|certainly|below is)\b.*:\s*$", re.I)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\$?\d[\d,]*(?:\.\d+)?(?:%|[KkMmBb]\b|\+)?")
_TERM_RE = re.compile(
    r"[A-Z][A-Za-z0-9+#]*(?:[/.-][A-Za-z0-9+#]+)*(?:\s\d+(?:\.\d+)?)?(?![A-Za-z0-9+#])"
)
_THIRD_PERSON_RE = re.compile(
    r"\b(?:he|she|his|her|hers|him|himself|herself)\b|\bthe candidate\b", re.I
)
_THEY_RE = re.compile(r"\b(?:they|them|their|theirs|themselves)\b", re.I)
_FIRST_PERSON_RE = re.compile(r"\bI\b|(?i:\b(?:my|me|myself|mine)\b)")
_DEPTH_RE = re.compile(
    r"\b(?:hands[\s-]on|expert(?:ise|ly)?|deep(?:ly)?|extensive(?:ly)?|advanced|"
    r"mastery|seasoned|proficient|specialist)\b",
    re.I,
)
_SNIPPET_LEN = 120
_REASONS = {
    "unsupported_number": "number not in the dossier text sent to the model",
    "unsupported_term": "name or term not in the dossier text sent to the model",
    "third_person": "third-person wording (a summary is first person)",
    "depth_claim": "depth claim the dossier text doesn't make",
}


@dataclass(frozen=True, slots=True)
class NarrativeFlag:
    """One sentence of a summary the user should review.

    Attributes:
        kind: ``"unsupported_number"``, ``"unsupported_term"``, ``"third_person"`` or
            ``"depth_claim"``.
        sentence: The sentence, verbatim.
        terms: The numbers, names or words that triggered the flag.
    """

    kind: str
    sentence: str
    terms: tuple[str, ...] = field(default_factory=tuple)

    def message(self) -> str:
        """Return a one-line, plain-text description of the flag."""
        snippet = self.sentence
        if len(snippet) > _SNIPPET_LEN:
            snippet = snippet[: _SNIPPET_LEN - 3] + "..."
        reason = _REASONS.get(self.kind, self.kind)
        return f'{", ".join(self.terms)}: {reason} -- "{snippet}"'

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable form."""
        return {"kind": self.kind, "sentence": self.sentence, "terms": list(self.terms)}


@dataclass(frozen=True, slots=True)
class NarrativeCheck:
    """The result of checking one generated summary.

    Attributes:
        text: The summary paragraph only, safe to show and export.
        removed: Text that was stripped (notes, extra paragraphs, headings), in order.
        flags: Sentences to review. Display only.
    """

    text: str
    removed: tuple[str, ...] = field(default_factory=tuple)
    flags: tuple[NarrativeFlag, ...] = field(default_factory=tuple)

    def report_lines(self) -> list[str]:
        """Return the plain-text lines shown to the user after a check."""
        lines = [f"Removed from the summary (not exported): {item}" for item in self.removed]
        lines += [f"Review: {flag.message()}" for flag in self.flags]
        return lines

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable form used by ``--json`` and the desktop bridge."""
        return {
            "text": self.text,
            "removed": list(self.removed),
            "flags": [flag.to_dict() for flag in self.flags],
        }


def _is_extra(line: str) -> bool:
    return bool(
        _RULE_RE.match(line)
        or _WRAPPED_NOTE_RE.match(line)
        or _NOTE_RE.match(line)
        or _HEADING_RE.match(line)
    )


def strip_extras(raw: str) -> tuple[str, tuple[str, ...]]:
    """Keep the summary paragraph and report everything else.

    Args:
        raw: The model's output.

    Returns:
        ``(summary, removed)``. If nothing recognizable is left as a summary, the
        stripped input is returned unchanged with nothing removed.
    """
    lines = raw.strip().splitlines()
    removed: list[str] = []
    start = 0
    while start < len(lines):
        line = lines[start]
        if not line.strip():
            start += 1
        elif _HEADING_RE.match(line) or _PREAMBLE_RE.match(line):
            removed.append(line.strip())
            start += 1
        else:
            break

    summary_lines: list[str] = []
    end = start
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            if summary_lines:
                break
        elif summary_lines and _is_extra(line):
            break
        else:
            summary_lines.append(line.strip())
        end += 1

    if not summary_lines:
        return raw.strip(), ()

    group: list[str] = []
    for line in [*lines[end:], ""]:
        if line.strip() and not _RULE_RE.match(line):
            group.append(line.strip())
        elif group:
            removed.append(" ".join(group))
            group = []
    return " ".join(summary_lines), tuple(removed)


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]


def _number_key(number: str) -> str:
    return number.replace(",", "").lower()


def _depth_key(word: str) -> str:
    return re.sub(r"[\s-]+", " ", word.lower())


def _term_is_checked(sentence: str, match: re.Match[str]) -> bool:
    term = match.group(0)
    if term == "I":
        return False
    leading = len(sentence) - len(sentence.lstrip("\"'([ "))
    if match.start() != leading:
        return True
    # A sentence's first word is capitalized anyway; check it only when it is
    # visibly a name (mixed case, an acronym, or has a digit).
    return any(ch.isupper() for ch in term[1:]) or any(ch.isdigit() for ch in term)


def check_narrative(raw: str, sent_text: str) -> NarrativeCheck:
    """Strip a generated summary down to its paragraph and flag claims to review.

    Args:
        raw: The model's output.
        sent_text: The dossier text that was sent to the model (not the job description).

    Returns:
        The cleaned text, what was removed, and the flags.
    """
    text, removed = strip_extras(raw)
    source_tokens = set(normalized_tokens(sent_text))
    source_numbers = {
        _number_key(m.group(0)) for m in _NUMBER_RE.finditer(normalize_text(sent_text))
    }
    source_depth = {_depth_key(m.group(0)) for m in _DEPTH_RE.finditer(sent_text)}

    flags: list[NarrativeFlag] = []
    for sentence in split_sentences(text):
        numbers = [
            m.group(0)
            for m in _NUMBER_RE.finditer(normalize_text(sentence))
            if _number_key(m.group(0)) not in source_numbers
        ]
        if numbers:
            flags.append(NarrativeFlag("unsupported_number", sentence, tuple(numbers)))

        terms = []
        for match in _TERM_RE.finditer(sentence):
            if not _term_is_checked(sentence, match):
                continue
            tokens = normalized_tokens(match.group(0))
            if tokens and not all(token in source_tokens for token in tokens):
                terms.append(match.group(0))
        if terms:
            flags.append(NarrativeFlag("unsupported_term", sentence, tuple(dict.fromkeys(terms))))

        pronouns = [m.group(0) for m in _THIRD_PERSON_RE.finditer(sentence)]
        if not _FIRST_PERSON_RE.search(sentence):
            pronouns += [m.group(0) for m in _THEY_RE.finditer(sentence)]
        if pronouns:
            flags.append(NarrativeFlag("third_person", sentence, tuple(dict.fromkeys(pronouns))))

        depth = [
            m.group(0)
            for m in _DEPTH_RE.finditer(sentence)
            if _depth_key(m.group(0)) not in source_depth
        ]
        if depth:
            flags.append(NarrativeFlag("depth_claim", sentence, tuple(dict.fromkeys(depth))))

    return NarrativeCheck(text=text, removed=removed, flags=tuple(flags))
