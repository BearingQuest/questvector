# 0020. The owner publishes releases; the workflow only creates a draft

- **Status:** Accepted; supersedes the auto-publish step and the tag-ruleset
  restrictions of [0014](0014-github-releases.md)
- **Date:** 2026-11-15

## Context
[ADR-0014](0014-github-releases.md) had `release.yml` publish the draft as its
last step (`gh release edit --draft=false`) and restricted who could create
`v*` tags with a ruleset that let the repository admin role bypass. Releases
are immutable once published (org and repository setting), so a published
mistake costs a version number. The project template, which this baseline
follows, keeps a human between a tag and a published release, and its tag
ruleset has no bypass actor.

## Decision
- `release.yml` builds, attests (`actions/attest`, unchanged) and then creates
  a **draft** pre-release. It never publishes. The owner checks the draft and
  publishes it by hand.
- Attestation runs before the draft is created, so a draft never lacks one.
- `--prerelease` stays while the README says proof of concept (backlog item 1).
- `.github/rulesets/tags.json` is renamed `release-tags.json` (the live ruleset
  is already named `release-tags`) and matches the template: no bypass actors,
  and `deletion`, `non_fast_forward` and `update` rules on `v*`. It no longer
  restricts creation, which retires 0014's admin-bypass exception. Only the
  owner creates tags by convention; agents are denied `git tag` in
  `.claude/settings.json` ([0019](0019-agent-permission-guardrails.md)).
- The rest of 0014 stands, including GitHub Releases as the only channel.

## Consequences
- A release needs one extra manual step, and a forgotten draft stays private.
- No path publishes without the owner, even if the workflow is compromised.
- Anyone with write access can now create a `v*` tag, which starts the
  workflow but can only produce a draft.
- The live `release-tags` ruleset differs from the file until the owner
  re-applies it (`docs/DEVELOPMENT.md`, Releasing).
