# 0027. One keyword normalization for postings, dossiers, and templates

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
Matching compares keyword sets (ADR-0006). The tokenizer kept "CI/CD" as
`ci/cd` while the DevOps template lists `cicd`; "SOC 2" became `soc` (and so
matched the cybersec template's `soc`, a security operations center) while the
template says `soc2`; "ISO 27001" became `iso`; "K8s" never met `kubernetes`.
A keyword at the end of a sentence kept its full stop (`kubernetes.`) and never
matched. Role titles in Chronology headings never counted at all.

Options considered for the variant list: in code, or an `aliases:` block in each
template. Template aliases would amend ADR-0003, repeat the same alias across
templates, and make a dossier normalize differently per template.

## Decision
One function, `questvector/core/normalize.py`, reduces text to tokens and is
applied identically to job-description text, dossier text, and template
keywords, so scoring stays symmetric.

- Lowercase; apply an ordered list of phrase rules (CI/CD, SOC 2, ISO 27001
  including ISO/IEC and the year, K8s, on-call, TCP/IP, cloud-native, PCI-DSS,
  infrastructure as code), each anchored with word boundaries so it can't fire
  inside another word ("k8sx", "SOC 20", "specific CD").
- Strip trailing `. - / _` from tokens; `c++`, `c#` and `node.js` are kept.
- The variant list lives in code, not in templates: one list for every
  template, no schema change. Adding a variant takes a release.
- Template loading normalizes each keyword. A keyword that isn't exactly one
  token afterwards raises the template validation error naming the template and
  the keyword; keywords that become duplicates collapse to one. No starter
  template changed.
- Chronology heading words (the role title) count as keywords. Capabilities and
  Impact headings do not: they are labels the user chose, not claims.

## Consequences
- This extends ADR-0006: the coverage formula is unchanged, only the keyword
  sets fed into it. A change to the formula itself (for example for score
  saturation, backlog item 1) would supersede ADR-0006.
- Compatibility: a custom mission template with a multi-word keyword that maps to
  no alias now fails to load and fails `qv template validate`, with an error
  naming the template and keyword. Before, it loaded, but such a keyword could
  never match.
- Scores for existing dossiers can rise: sentence-final keywords and the new
  variants now match. "SOC 2" no longer matches `soc`.
- Accepted false positive: "on call" in ordinary prose ("relies on call logs")
  becomes `oncall`.
- No stemming: "pipeline" and "pipelines" remain different keywords.
- Still open (backlog item 1): negated skills and score saturation. Both are
  pinned by characterization tests until decided.
