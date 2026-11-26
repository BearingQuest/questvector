# 0030. Negation warnings and asked-keyword counts

- **Status:** Accepted
- **Date:** 2026-11-26

## Context
Owner decisions, 25 Nov 2026 (backlog item 1, part 2). Two things the match could not show:

- **Negated skills.** Matching is by keyword (ADR-0006), and `not` is a stopword that `tokenize()` drops, so "No hands-on Kubernetes" counts as a Kubernetes match, and the narrative prompt can present it as a skill.
- **What the score is out of.** A large dossier covers every keyword a template lists, so the score stops telling postings apart (score saturation). The score gave no hint of how many keywords the posting actually asked about.

Options for negation: document the rule in the README; warn; or an exclusions section that matching ignores. Options for saturation: show "N of M" next to the score (display only), or change the formula.

## Decision
Display only. **The score, the alert level and the ADR-0006 formula are unchanged.** See also [ADR-0006](0006-independent-g-force-formula.md) and [ADR-0027](0027-keyword-normalization.md).

**Asked-keyword counts.** Per category, N = the posting's keywords that the category lists and the dossier has (`matched_keywords`), M = N plus `gap_keywords`. Shown as "N of M asked"; when M is 0, "not asked (counts as full coverage)". The overall line is "N of M template keywords in this posting are in your dossier", where N and M count distinct keywords across categories (one keyword in two categories counts once). M counts only the posting's keywords that the template lists, not every word the posting uses. A category with no keywords asks about every posting keyword, so M includes them. Computed once, as properties on `CategoryScore` and `MatchResult`, and shown in the CLI text, `--json`, the desktop window and the PDF and DOCX exports (including exports made from the window).

**Negation warnings.** `questvector/core/negation.py`, run by `run_match`, stored on `MatchResult.negation_warnings`. Each warning names the file, the heading, the line and the keywords.
- Lines checked: every Capability, every Chronology heading and bullet (the heading counts since ADR-0027), every Impact bullet. Capabilities and Impact headings are labels, not claims, and are not checked.
- The line is normalized the ADR-0027 way (so "K8s" is `kubernetes`), then split into clauses at `. , ; :` followed by whitespace or the end of the line (so `node.js` stays one token) and at the word "but".
- Cues: `no`, `not`, `never`, `without`, `none`, and the phrase "training only". A leading cue flags a matched keyword at most 4 tokens after it in the same clause; "training only" flags a matched keyword at most 4 tokens before it. "not only" and "not just" are not cues. Four tokens covers "No production experience with Kubernetes" and "Never used HashiCorp Vault"; more reaches across ideas.
- Only keywords that matched for this posting are flagged.
- Not added: `limited`, `basic`, `little`, `lack`. A limited skill is still a claim, and broad words would bury real warnings.
- Shown in the `qv sync-ast` text and `--json`, and in the desktop result as its own list. Not in exports, which are meant to be shared. The desktop renders the list as text (ADR-0029).

**One serializer.** `MatchResult.to_dict()` builds the dict for both `qv sync-ast --json` and the desktop bridge. Every existing key and value is unchanged; new keys are `matched_count`, `asked_count`, `counts_text`, `negation_warnings`, and per category `matched_count`, `asked_count`, `counts_text`. The desktop gains `weak_categories`, which PRD R3 already promised and the bridge had omitted.

**Template keywords.** A template keyword that `tokenize()` would drop (a stopword or one letter, for example "it") now fails template loading and `qv template validate`, naming the template, category and keyword, because it loaded before but could never match. No starter or boilerplate keyword is affected.

The exclusions section was not built. It is the only option that also keeps the text out of the narrative; it remains open in backlog item 1.

## Consequences
- A negated line still counts toward the score and still reaches the narrative prompt. The warning only tells the owner to remove it. The README says to leave such statements out.
- **Accepted false positives** (each pinned by a test): "No downtime during the Kubernetes migration" is flagged for `kubernetes`; a line is flagged even when another line claims the same keyword.
- **Not handled** (each pinned by a test): contractions ("don't", "haven't", with a straight or a curly apostrophe), because the tokenizer stops at the apostrophe and handling them takes a separate rule; a cue more than 4 tokens before its keyword ("No A B C D Kubernetes"); a trailing "none" ("Kubernetes: none"); and "No. 1 ranked Kubernetes team", where "No." ends a clause so the cue never reaches the keyword (it does not warn).
- **Finding for the later formula decision (backlog item 1, saturation).** A category the posting never asks about counts as 100% coverage at its full weight (PRD R4: it SHALL NOT lower the score). Measured on synthetic data with devops-senior-mgr and a 120-bullet dossier: the on-target posting is asked 12 keywords and the off-target posting 7, and both score 100.0; off-target, `cicd_automation` (weight 0.2) is asked 0 keywords and still counts as full coverage. The asked counts make that visible. Whether to change the formula stays open until the owner has run it on real postings; a change would supersede ADR-0006.
- Revisit: contractions, if real dossiers use them; the 4-token window, after real use.
