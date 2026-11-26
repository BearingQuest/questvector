# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub: on the repository's
**Security** tab, choose **Report a vulnerability**, or go straight to
<https://github.com/BearingQuest/questvector/security/advisories/new>.
Don't open a public issue for a security problem.

Include what you found, the steps to reproduce it, and the version or commit
you tested. This is a one-person project, so replies may take a few days.

## Scope

QuestVector runs locally and has no hosted service
([ADR-0001](docs/decisions/0001-local-only-distribution.md)). Issues of
particular interest:
- the encrypted vault (`questvector/core/vault.py`), including key
  derivation and how keys are stored or shown;
- what dossier content is sent to a remote AI provider during narrative
  generation (`questvector/core/llm.py`);
- reading or writing files outside the workspace.

## Supported versions

The latest release (currently 1.2.0) and the latest commit on `main` are
supported. Older releases (1.1.0 and earlier) are not; upgrade to the latest
release.
