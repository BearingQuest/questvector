"""AGENT-01..08: .claude/settings.json keeps every deny, ask and sandbox key, and allows nothing.

The only command excluded from the sandbox is gh. AGENTS.md carries the rules the settings
cannot enforce, and CLAUDE.md imports it (ADR-0019, ADR-0024). The rules match command text,
so they are a guardrail; the sandbox and the GitHub rulesets are the enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
SCHEMA = "https://json.schemastore.org/claude-code-settings.json"

MODE_LOCKS = ["disableAutoMode", "disableBypassPermissionsMode"]

REQUIRED_DENY = [
    # gh pr merge, and the script that wraps it (the gh deny cannot see inside it)
    "Bash(gh pr merge)",
    "Bash(gh pr merge *)",
    "Bash(gh * pr merge)",
    "Bash(gh * pr merge *)",
    "Bash(bq-merge)",
    "Bash(bq-merge *)",
    # gh pr review covers --approve (ADR-0019)
    "Bash(gh pr review)",
    "Bash(gh pr review *)",
    "Bash(gh * pr review)",
    "Bash(gh * pr review *)",
    # force pushes, plain and option-first
    "Bash(git push --force*)",
    "Bash(git push -f*)",
    "Bash(git push * --force*)",
    "Bash(git push * -f*)",
    "Bash(git push * +*)",
    "Bash(git * push --force*)",
    "Bash(git * push -f*)",
    "Bash(git * push * --force*)",
    "Bash(git * push * -f*)",
    "Bash(git * push * +*)",
    # recursive force deletes
    "Bash(rm -rf)",
    "Bash(rm -rf *)",
    "Bash(rm -fr)",
    "Bash(rm -fr *)",
    "Bash(rm -r -f)",
    "Bash(rm -r -f *)",
    "Bash(rm -f -r)",
    "Bash(rm -f -r *)",
    "Bash(rm -Rf)",
    "Bash(rm -Rf *)",
    "Bash(rm -fR)",
    "Bash(rm -fR *)",
    # terraform
    "Bash(terraform apply)",
    "Bash(terraform apply *)",
    "Bash(terraform * apply)",
    "Bash(terraform * apply *)",
    "Bash(terraform destroy)",
    "Bash(terraform destroy *)",
    "Bash(terraform * destroy)",
    "Bash(terraform * destroy *)",
    # repository, Actions, security and Pages settings, secrets
    "Bash(gh api *rulesets*)",
    "Bash(gh api *actions/permissions*)",
    "Bash(gh api *code-security*)",
    "Bash(gh api *environments*)",
    "Bash(gh api *actions/secrets*)",
    "Bash(gh api *pages*)",
    "Bash(gh secret)",
    "Bash(gh secret *)",
    "Bash(gh repo create)",
    "Bash(gh repo create *)",
    "Bash(gh repo edit)",
    "Bash(gh repo edit *)",
    # releases: `gh release *` covers create, edit (--draft=false publishes), delete, upload
    "Bash(gh release)",
    "Bash(gh release *)",
    # gh runs outside the sandbox, so nothing stops it printing its token but these
    "Bash(gh auth token*)",
    "Bash(gh auth status *--show-token*)",
    "Bash(gh auth status *-t*)",
    # tags
    "Bash(git tag)",
    "Bash(git tag *)",
    "Bash(git * tag)",
    "Bash(git * tag *)",
    "Bash(git push *--tags*)",
    "Bash(git * push *--tags*)",
    "Bash(git push *--follow-tags*)",
    "Bash(git * push *--follow-tags*)",
]

# Options before the subcommand (`gh -R owner/repo release create`) slip past the plain
# `gh release *` rule. These are the four forms ADR-0019 denied; a broader `gh * release *`
# would also block any gh command whose text mentions a release.
OPTION_FIRST_RELEASE_DENY = [
    "Bash(gh * release create)",
    "Bash(gh * release create *)",
    "Bash(gh * release edit)",
    "Bash(gh * release edit *)",
    "Bash(gh * release delete)",
    "Bash(gh * release delete *)",
    "Bash(gh * release upload)",
    "Bash(gh * release upload *)",
]

REQUIRED_READ_DENY = [
    "Read(~/.ai_post_env)",
    "Read(~/.aws/**)",
    "Read(~/.ssh/**)",
    "Read(~/.config/gh/**)",
    "Read(~/career-workspace/**)",
    "Read(./.env)",
    "Read(./.env.*)",
]

# Edit rules cover every built-in file-editing tool, Write included; Write(path)
# rules do not match anything, so the settings files are protected with Edit.
REQUIRED_EDIT_DENY = [
    "Edit(/.claude/settings.json)",
    "Edit(/.claude/settings.local.json)",
    "Edit(~/.claude/settings.json)",
    "Edit(//Library/Application Support/ClaudeCode/**)",
]

REQUIRED_ASK = [
    "Bash(git push)",
    "Bash(git push *)",
    "Bash(git * push)",
    "Bash(git * push *)",
    "Bash(gh pr)",
    "Bash(gh pr *)",
    "Bash(gh * pr)",
    "Bash(gh * pr *)",
    "Bash(gh api)",
    "Bash(gh api *)",
    "Bash(gh * api)",
    "Bash(gh * api *)",
    "Bash(python3)",
    "Bash(python3 *)",
]

# gh cannot read its login in ~/.config/gh from inside the sandbox, so it runs
# outside it. The entry needs the trailing " *": a bare "gh" matches only `gh` with
# no arguments. Nothing else may be excluded; the deny and ask rules above still apply.
SANDBOX_EXCLUDED_COMMANDS = ["gh *"]

# Sandbox paths differ from Read()/Edit() rules: "/" is absolute, "~/" is home,
# "./" is the project root.
SANDBOX_FLAGS = {
    "enabled": True,
    "failIfUnavailable": True,
    "allowUnsandboxedCommands": False,
    "autoAllowBashIfSandboxed": False,
}

SANDBOX_DENY_READ = {
    "~/.ai_post_env",
    "~/.aws",
    "~/.ssh",
    "~/.config/gh",
    "~/career-workspace",
    "./.env",
    "./.env.*",
}

# An Edit() deny does not stop a shell redirect, so the settings files are
# also write-denied for sandboxed commands.
SANDBOX_DENY_WRITE = {
    "./.claude/settings.json",
    "./.claude/settings.local.json",
    "~/.claude/settings.json",
    "/Library/Application Support/ClaudeCode",
}

# uv's cache: `uv sync`, `uv run` and `uv export` write there. Python 3.14 is
# already installed under ~/.local/share/uv/python, so nothing else is needed.
SANDBOX_ALLOW_WRITE = {"~/.cache/uv"}

SANDBOX_ALLOWED_DOMAINS = {
    "pypi.org",  # dependency resolution and pip-audit lookups
    "files.pythonhosted.org",  # wheel downloads
    "github.com",
    "api.github.com",
}


@pytest.fixture(scope="module")
def settings() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return data


def _agents_text() -> str:
    return " ".join((REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8").split())


def test_schema_is_declared(settings: dict[str, Any]) -> None:
    assert settings["$schema"] == SCHEMA


@pytest.mark.parametrize("key", MODE_LOCKS)
def test_mode_is_disabled(settings: dict[str, Any], key: str) -> None:
    assert settings["permissions"][key] == "disable"


@pytest.mark.parametrize("rule", REQUIRED_DENY + OPTION_FIRST_RELEASE_DENY)
def test_deny_rule_present(settings: dict[str, Any], rule: str) -> None:
    assert rule in settings["permissions"]["deny"]


def test_no_option_first_gh_auth_deny(settings: dict[str, Any]) -> None:
    # "Bash(gh * auth token*)" matches any gh command whose text mentions "auth token",
    # including `gh pr create` with that phrase in its title or body, so it silently
    # refuses legitimate calls. Only the plain "gh auth ..." forms may be denied.
    option_first = [
        rule
        for rule in settings["permissions"]["deny"]
        if rule.startswith("Bash(gh *") and "auth" in rule
    ]
    assert option_first == []


@pytest.mark.parametrize("rule", REQUIRED_READ_DENY)
def test_read_deny_rule_present(settings: dict[str, Any], rule: str) -> None:
    assert rule in settings["permissions"]["deny"]


@pytest.mark.parametrize("rule", REQUIRED_EDIT_DENY)
def test_edit_deny_rule_present(settings: dict[str, Any], rule: str) -> None:
    assert rule in settings["permissions"]["deny"]


@pytest.mark.parametrize("rule", REQUIRED_ASK)
def test_ask_rule_present(settings: dict[str, Any], rule: str) -> None:
    assert rule in settings["permissions"]["ask"]


def test_every_prefix_rule_has_its_bare_form(settings: dict[str, Any]) -> None:
    # A trailing " *" does not reliably match the command with no arguments, so every
    # `Bash(<command> *)` rule is paired with `Bash(<command>)` in the same list.
    for kind in ("deny", "ask"):
        rules = settings["permissions"][kind]
        for rule in rules:
            if rule.startswith("Bash(") and rule.endswith(" *)"):
                bare = rule.removesuffix(" *)") + ")"
                assert bare in rules, f"{kind}: {rule} has no bare form {bare}"


@pytest.mark.parametrize(("key", "value"), SANDBOX_FLAGS.items())
def test_sandbox_flag(settings: dict[str, Any], key: str, value: bool) -> None:
    assert settings["sandbox"][key] is value


@pytest.mark.parametrize(
    ("section", "key", "expected"),
    [
        ("filesystem", "denyRead", SANDBOX_DENY_READ),
        ("filesystem", "denyWrite", SANDBOX_DENY_WRITE),
        ("filesystem", "allowWrite", SANDBOX_ALLOW_WRITE),
        ("network", "allowedDomains", SANDBOX_ALLOWED_DOMAINS),
    ],
)
def test_sandbox_list_is_exact(
    settings: dict[str, Any], section: str, key: str, expected: set[str]
) -> None:
    # Set equality: a path or host added without updating this test fails too.
    assert set(settings["sandbox"][section][key]) == expected


def test_sandbox_excluded_commands_is_exact(settings: dict[str, Any]) -> None:
    # List equality: any extra, missing or reordered entry fails.
    assert settings["sandbox"]["excludedCommands"] == SANDBOX_EXCLUDED_COMMANDS


def test_strict_allowlist_is_not_in_repo_file(settings: dict[str, Any]) -> None:
    # sandbox.network.strictAllowlist only takes effect from user or managed
    # settings, so a copy here would do nothing and look like protection.
    # The owner sets it in managed settings (see AGENTS.md).
    assert "strictAllowlist" not in settings["sandbox"]["network"]


def test_no_allow_rules(settings: dict[str, Any]) -> None:
    assert "allow" not in settings
    assert not settings["permissions"].get("allow")


def test_agents_md_tells_the_agent_to_run_gh_on_its_own() -> None:
    # AGENT-06: only a plain gh call matches excludedCommands and leaves the sandbox,
    # so AGENTS.md must say not to wrap it in cd, &&, ;, pipes or redirects.
    text = _agents_text()
    assert "Run every `gh` command on its own: no `cd`, `&&`, `;`, pipes or redirects." in text
    assert "Only a plain `gh` call runs outside the sandbox" in text


def test_agents_md_forbids_reading_career_workspace() -> None:
    assert "**Never read `~/career-workspace`**" in _agents_text()


def test_agents_md_names_the_managed_settings_for_strict_allowlist() -> None:
    assert "/Library/Application Support/ClaudeCode/managed-settings.json" in _agents_text()


def test_claude_md_imports_agents_md() -> None:
    lines = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "@AGENTS.md"
