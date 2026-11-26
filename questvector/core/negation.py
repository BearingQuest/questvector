"""Negation warnings: dossier lines that deny a skill the match still counted (ADR-0030).

Matching is by keyword, so "No hands-on Kubernetes" counts as a Kubernetes
match. This module flags such lines. It never changes a score, a gap or an alert
level: it only reports.

Rule, applied to each dossier line that can supply keywords (every Capability,
every Chronology heading and bullet, every Impact bullet):
    1. Normalize the line the ADR-0027 way (so "K8s" is ``kubernetes``).
    2. Split it into clauses at ``. , ; :`` when followed by whitespace or the end
       of the line (so ``node.js`` stays one token), and at the word "but".
    3. In each clause, a leading cue (:data:`_LEADING_CUES`) flags a matched
       keyword at most :data:`_WINDOW` tokens after it, and the phrase
       "training only" flags a matched keyword at most :data:`_WINDOW` tokens
       before it. "not only" and "not just" are not cues.
    4. Only keywords that matched for this posting are flagged.

Not handled (each pinned by a test): contractions ("don't", "haven't"), a cue
more than :data:`_WINDOW` tokens before its keyword, and a trailing "none"
("Kubernetes: none"). Accepted false positives: "No downtime during the
Kubernetes migration" and any line whose keyword is also claimed on another line.
"""

from __future__ import annotations

import re

from questvector.config import CAPABILITIES_FILENAME, CHRONOLOGY_FILENAME, IMPACT_FILENAME
from questvector.core.models import Dossier, NegationWarning
from questvector.core.normalize import normalize_text, normalized_tokens

_LEADING_CUES = frozenset({"no", "not", "never", "without", "none"})
_NOT_CUE_FOLLOWERS = frozenset({"only", "just"})
_WINDOW = 4
_CLAUSE_BREAK_RE = re.compile(r"[.,;:](?=\s|$)|\bbut\b")


def _flagged_keywords(line: str, matched: frozenset[str]) -> tuple[str, ...]:
    """Return the matched keywords that a negation cue sits next to in ``line``.

    Args:
        line: One dossier line (a bullet, a capability or a heading).
        matched: The keywords that matched for this posting.

    Returns:
        The flagged keywords, sorted; empty when the line has none.
    """
    flagged: set[str] = set()
    for clause in _CLAUSE_BREAK_RE.split(normalize_text(line)):
        tokens = normalized_tokens(clause)
        for i, word in enumerate(tokens):
            following = tokens[i + 1 : i + 1 + _WINDOW]
            if word in _LEADING_CUES and not (
                word == "not" and following[:1] and following[0] in _NOT_CUE_FOLLOWERS
            ):
                flagged.update(t for t in following if t in matched)
            if word == "training" and tokens[i + 1 : i + 2] == ["only"]:
                flagged.update(t for t in tokens[max(0, i - _WINDOW) : i] if t in matched)
    return tuple(sorted(flagged))


def find_negation_warnings(
    dossier: Dossier, matched: frozenset[str]
) -> tuple[NegationWarning, ...]:
    """Find dossier lines that negate a keyword that matched for this posting.

    Args:
        dossier: The parsed dossier.
        matched: The keywords that matched, across all template categories.

    Returns:
        One :class:`NegationWarning` per flagged line, in dossier order
        (Capabilities, then Chronology, then Impact).
    """
    lines: list[tuple[str, str, str]] = []
    lines.extend((CAPABILITIES_FILENAME, c.domain, c.text) for c in dossier.capabilities)
    for entry in dossier.chronology:
        lines.append((CHRONOLOGY_FILENAME, entry.heading, entry.heading))
        lines.extend((CHRONOLOGY_FILENAME, entry.heading, b) for b in entry.bullets)
    for stmt in dossier.impact:
        lines.extend((IMPACT_FILENAME, stmt.heading, b) for b in stmt.bullets)

    warnings: list[NegationWarning] = []
    for file, heading, text in lines:
        keywords = _flagged_keywords(text, matched)
        if keywords:
            warnings.append(
                NegationWarning(file=file, heading=heading, line=text, keywords=keywords)
            )
    return tuple(warnings)
