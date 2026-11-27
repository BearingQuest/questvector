# 0032. Summary guardrails, resume-style export and a check of the exported file

- **Status:** Accepted
- **Date:** 2026-11-27

## Context
Owner decisions, 27 Nov 2026 (backlog item 5): build the guardrails (PRD R14), a resume-style export that screening software can read (R9) and a check of the exported file (R10) in one pull request, as three commits. The guardrails flag and strip but don't block. The 20-year cutoff is opt-in. The desktop export keeps no summary for now (CLI only).

Why: the 5 Nov 2026 Anthropic live run appended an italic note naming the trap keywords after an accurate summary ([ADR-0018](0018-anthropic-thinking-off.md)); the Ollama runs invented facts and added "Here is..." preambles ([ADR-0012](0012-ollama-thinking-off.md)); the 27 Oct real-dossier run inflated depth ("hands-on") and merged facts across roles. Today's export is a private match report plus the whole dossier, not a resume.

## Decision

### Part 1: summary guardrails (R14)
- **Prompt.** `_NARRATIVE_SYSTEM_PROMPT` and the user-turn tail in `questvector/core/llm.py` ask for one first-person paragraph only (no heading, preamble, note, list or markdown, nothing after it), only facts in the excerpts, no titles, metrics, numbers, dates, durations, employers or technologies that aren't there, no depth claim ("hands-on", "expert", "deep") the excerpts don't make, and say the job description shows what to emphasize but is not a source of facts about the candidate. Provider-neutral; the thinking settings of ADR-0012 and ADR-0018 are untouched. `dossier_context_for_prompt` is now the one place that builds the text sent (the first 20 capability bullets), used by the CLI, the desktop and the check.
- **Output check** (`questvector/core/guardrails.py`), run on every generated summary before it is shown or exported:
  - *Strip*, and report what was removed: a heading or "Here is ...:" line before the summary; after it, a second paragraph, a horizontal rule, a whole-line italic, bracketed or parenthesised note, a "Note:" line. If nothing recognizable would be left, the text is kept as is.
  - *Flag, don't block*, per sentence: a **number** not in the sent text (compared exactly after dropping commas; "31%", "$1.8M", "7+"); a **capitalized name or technology term** not in the sent text (mid-sentence capitalized words, acronyms and mixed-case words, each with an optional following number, so "SOC 2" and "ISO 27001" are single terms); **third-person pronouns** (he, she, his, her, hers, him, himself, herself, "the candidate"; they, them, their, theirs and themselves only when the sentence has no first-person word); a **depth word** (hands-on, expert, expertise, deep, extensive, advanced, mastery, seasoned, proficient, specialist) the sent text doesn't use.
  - *"Appears in the dossier"* means the text that was sent to the model (not the job description, not Chronology), normalized the [ADR-0027](0027-keyword-normalization.md) way: every token of the term, after `normalized_tokens`, is in the sent text's token set. So "K8s", "CI/CD" and "SOC 2" meet "Kubernetes", "cicd" and "soc2". A digit inside a word ("K8s", "S3") is not a number.
  - Flags show in `qv export` output, in `qv export --json` (new; `narrative` holds `text`, `removed`, `flags`) and in the desktop result (`narrative`, `removed`, `flags`), rendered as text ([ADR-0029](0029-desktop-text-only-csp-bundle-names.md)). The export still runs. Flags never go into the exported file: the exporter only receives the cleaned text.

## Consequences
- **Accepted false positives** (each pinned by a test): naming the target employer from the posting ("I want to bring my AWS skills to Quillon Systems") is flagged; a capitalized common noun mid-sentence is flagged; singular and plural forms of a capitalized word don't match each other (no stemming, as in ADR-0027); "expertise" is flagged when the dossier says "expert".
- **Accepted misses** (each pinned by a test): a sentence-initial plain capitalized word ("Datadog dashboards ...") isn't checked; spelled-out numbers ("seven years") aren't; lowercase technology names aren't; "they" about a team after "I" is not flagged; an invented fact in common words isn't caught. The check is a review aid, not proof that a summary is accurate.
- The check cannot know the model's output is true, only what it contains that the dossier text doesn't.
