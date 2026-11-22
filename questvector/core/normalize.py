"""Keyword normalization shared by job descriptions, dossiers, and templates.

The matcher compares keyword sets, so a posting that says "CI/CD" and a
template that lists ``cicd`` only meet if both sides are reduced to the same
form. This module is that single reduction (ADR-0027). It is applied
identically to job-description text, dossier text, and template keywords, so
scoring stays symmetric.

Rules, in order:
    1. Lowercase the text.
    2. Apply the phrase rules below. Each is anchored with word boundaries so
       it cannot fire inside another word ("k8sx", "SOC 20" and "specific CD"
       are left alone).
    3. Split into tokens that start with a letter and may contain digits and
       ``+ . # / _ -``.
    4. Strip trailing ``. - / _`` from each token, so the last word of a
       sentence ("Kubernetes.") matches the same word mid-sentence, while
       ``c++``, ``c#`` and ``node.js`` keep their punctuation.

Only the standard library is used, and there is no stemming: "pipeline" and
"pipelines" remain different keywords. One accepted false positive: "on call"
in ordinary prose ("relies on call logs") becomes ``oncall``.
"""

from __future__ import annotations

import re

#: Ordered ``(pattern, replacement)`` rules applied to lowercased text. Every
#: replacement is a keyword form the starter templates use. Add a rule here
#: (not in a template) so every template and every dossier normalizes alike.
_PHRASE_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), replacement)
    for pattern, replacement in (
        (r"\bci\s*[/-]?\s*cd\b", "cicd"),
        (r"\bsoc\s*-?\s*2\b", "soc2"),
        (r"\biso(?:/iec)?\s*-?\s*27001(?::\d{4})?\b", "iso27001"),
        (r"\bk8s\b", "kubernetes"),
        (r"\bon[\s-]call\b", "oncall"),
        (r"\btcp\s*[/-]?\s*ip\b", "tcpip"),
        (r"\bcloud[\s-]native\b", "cloudnative"),
        (r"\bpci[\s-]dss\b", "pci"),
        (r"\binfrastructure[\s-]as[\s-]code\b", "iac"),
    )
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/_-]*")
_TRAILING_PUNCTUATION = ".-/_"


def normalize_text(text: str) -> str:
    """Lowercase ``text`` and rewrite known variants to their canonical form.

    Args:
        text: Arbitrary text (a bullet, a job description, a template keyword).

    Returns:
        The lowercased text with each phrase rule applied.
    """
    normalized = text.lower()
    for pattern, replacement in _PHRASE_RULES:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def normalized_tokens(text: str) -> list[str]:
    """Split ``text`` into normalized tokens, in order, without filtering.

    Stopwords and short tokens are not removed here; that is
    :func:`questvector.core.markdown_parser.tokenize`'s job. Template loading
    uses this unfiltered form to check that a keyword is exactly one token.

    Args:
        text: Arbitrary text.

    Returns:
        The normalized tokens with trailing punctuation removed.
    """
    return [
        match.group(0).rstrip(_TRAILING_PUNCTUATION)
        for match in _TOKEN_RE.finditer(normalize_text(text))
    ]
