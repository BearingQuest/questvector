# 0033. Score as coverage plus relevance, and a low-relevance alert level

- **Status:** Accepted; partly supersedes [0006](0006-independent-g-force-formula.md) (the not-asked-category rule)
- **Date:** 2026-11-28

## Context
Owner decision, 28 Nov 2026 (backlog item 1, "Score saturation"). Until now a category the posting never asks about counted as 100% coverage at its full weight (PRD R4; [ADR-0030](0030-negation-warnings-and-asked-keyword-counts.md) recorded it), so the score rose with every category the posting skipped.

Evidence: the owner's run on 28 Nov 2026, real dossier, `devops-senior-mgr` (36 keywords in 5 categories). Numbers only, no posting text:

| Posting | Keywords asked | Categories asked | Score then |
|---|---|---|---|
| 1, strong fit | 18 of 36 | 5 | 96.0% |
| 2, LinkedIn feed | 15 of 36 | 4 (security not asked) | 87.3% |
| 3, hourly-job search | 2 of 36 (both leadership) | 1 | 100.0%, SUCCESS |

A posting that asks about two keywords scored a clean SUCCESS.

## Decision
Option C, two numbers and a new alert level.

- **Coverage** is the weighted score over the categories the posting asks about only, divided by those categories' weights. A category with nothing relevant in the posting is left out of the score and of the denominator. `g_force_score` now holds this number. The other rules of ADR-0006 stand: per-category coverage, red flag on a heavy category with zero coverage, gaps, weak categories (these already came only from asked categories). Expected on the table: posting 1 96.0%, posting 2 85.9% (0.7733 / 0.9), posting 3 100%.
- **Relevance** is the distinct template keywords the posting asks about, over the distinct template keywords, after the [ADR-0027](0027-keyword-normalization.md) normalization. A keyword listed in two categories counts once. Expected: 50%, 41.7% (shown as 42%), 5.6% (shown as 6%).
- **`LOW_RELEVANCE`** (`low_relevance` in JSON) is set when fewer than `MATCH_MIN_ASKED_KEYWORDS` (5) template keywords or fewer than `MATCH_MIN_ASKED_CATEGORIES` (2) categories are asked. Each minimum is capped by the template's own size (`min(5, distinct template keywords)`, `min(2, categories)`), so a small custom template that is fully asked is not low. Order: red flags give CRITICAL (unchanged); else low relevance; else the existing rules (score below 40 is CRITICAL; gaps, weak categories or a score below 70 are WARNING; else SUCCESS). The constants are in `config.py` beside `MATCH_WARNING_SCORE`.
- **Nothing asked.** With no template keyword asked there is no coverage number: `coverage` is `null`, `g_force_score` is `0.0` (kept a number for older readers), and every surface says "no template keywords found", never 100% or 0%.
- **Low relevance is not scored in anything a person reads.** The CLI headline is `G-Force Match: not scored (low relevance)`, the window gauge shows `--`, the report PDF and DOCX use the same words, and category lines and table cells show no percentage. Relevance (with its percentage) and the note are shown instead. `coverage` and `g_force_score` stay in `--json` as computed. (First build showed "100.0% coverage (LOW_RELEVANCE)" for a 2-keyword posting; that read as a score and was fixed before release.)
- **Where it shows.** `qv sync-ast` (coverage, relevance, alert level, and a plain note with a suggestion to try another template; the exit code is 0, as for WARNING), `--json` and the desktop window (from the one serializer, `MatchResult.to_dict`), and the report-style PDF and DOCX. The resume style shows no score ([ADR-0032](0032-summary-guardrails-resume-export-file-check.md)). In the window LOW_RELEVANCE uses the muted text color (`muted` in `docs/design/tokens.json`), not the warning amber, and shows the words "LOW RELEVANCE".

## Compatibility
`--json` gains `coverage`, `relevance`, `low_relevance`, `asked_template_count`, `template_keyword_count`, `asked_category_count` and four text keys (`coverage_text`, `category_coverage_texts`, `relevance_text`, `relevance_note`). Two existing keys change meaning: `g_force_score` (coverage over asked categories, so a posting that skips a category scores lower than before) and `alert_level` (a fourth value, `low_relevance`). A category's `counts_text` for a not-asked category now reads "not asked (left out of the score)".

## Consequences
- The three postings above no longer look alike: posting 3 reads as "this template barely applies".
- The thresholds (5 keywords, 2 categories) are starting values from three postings, not tuned. They are per app, not per template (only the size cap adapts), so a template with 40 keywords and one with 8 use the same 5.
- A short posting can be low relevance even when it is a good fit for the role.
- Keyword matching still can't judge seniority or depth ([ADR-0006](0006-independent-g-force-formula.md)); a high coverage number is a guide, not a verdict.
- Other formula options in backlog item 1 (recency, more than one mention, counting only Chronology or Impact evidence) are not built.
- The [ADR-0030](0030-negation-warnings-and-asked-keyword-counts.md) line "the score, the alert level and the formula are unchanged" was true then and stays as history.
