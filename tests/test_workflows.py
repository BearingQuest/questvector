"""Checks on the GitHub Actions workflow files.

Every workflow pins its actions to a commit SHA with a version comment and
keeps the checkout token out of the working copy (ADR-0011). The release
workflow runs only on v* tags, and only its release job can write
(ADR-0014). Comments are lost when YAML is parsed, so the pin check reads
the raw text.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"
RULESETS = Path(__file__).parent.parent / ".github" / "rulesets"
# The GitHub Actions app, which reports the required checks.
GITHUB_ACTIONS_APP_ID = 15368
REQUIRED_CHECKS = {
    "pytest (full, Python 3.14)",
    "pytest (minimal, Python 3.14)",
    "ruff and mypy",
    "Validate mission templates",
    "gitleaks",
    "semgrep",
    "pip-audit",
    "zizmor",
}
WORKFLOW_FILES = sorted(WORKFLOWS.glob("*.yml"))
DAILY = WORKFLOWS / "pip-audit-daily.yml"
SCORECARD = WORKFLOWS / "scorecard.yml"
REVIEW = WORKFLOWS / "claude-review.yml"
RELEASE = WORKFLOWS / "release.yml"
SECURITY = WORKFLOWS / "security.yml"
DEPENDABOT = Path(__file__).parent.parent / ".github" / "dependabot.yml"
# These start from no permissions and grant each job its own (ADR-0022).
NO_DEFAULT_TOKEN = {"scorecard.yml", "claude-review.yml"}
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s+# v\d+\.\d+\.\d+$")


def _load(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(workflow: dict[Any, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def test_workflow_files_found() -> None:
    assert WORKFLOWS / "release.yml" in WORKFLOW_FILES


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_actions_pinned_to_sha_with_version_comment(path: Path) -> None:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = USES_LINE.match(line)
        if match:
            ref, rest = match.groups()
            assert PINNED.match(ref), f"{path.name}:{number}: {ref} is not pinned to a commit SHA"
            assert VERSION_COMMENT.match(rest), f"{path.name}:{number}: missing '# vX.Y.Z' comment"


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_checkout_does_not_persist_credentials(path: Path) -> None:
    for step in _steps(_load(path)):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, path.name


def test_release_runs_only_on_version_tags() -> None:
    workflow = _load(WORKFLOWS / "release.yml")
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    assert workflow[True] == {"push": {"tags": ["v*"]}}


def _jobs(path: Path) -> dict[str, dict[str, Any]]:
    jobs = _load(path)["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def test_release_permissions() -> None:
    workflow = _load(WORKFLOWS / "release.yml")
    assert workflow["permissions"] == {"contents": "read"}
    # No job block: the build job inherits the workflow's read-only grant.
    assert "permissions" not in workflow["jobs"]["build"]
    assert workflow["jobs"]["release"]["permissions"] == {
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }


def test_release_job_runs_no_repository_code() -> None:
    steps = _load(WORKFLOWS / "release.yml")["jobs"]["release"]["steps"]
    assert not any(str(step.get("uses", "")).startswith("actions/checkout@") for step in steps)


def test_release_creates_a_draft_and_never_publishes_it() -> None:
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    steps = _load(WORKFLOWS / "release.yml")["jobs"]["release"]["steps"]
    create = next(step["run"] for step in steps if "gh release create" in step.get("run", ""))
    for flag in ("--draft", "--verify-tag", "--prerelease"):
        assert flag in create
    assert "--latest" not in create
    # Publishing is the owner's step (ADR-0020).
    assert "gh release edit" not in text
    assert "--draft=false" not in text
    # Attested before the draft exists.
    uses = [step.get("uses", "") for step in steps]
    attest = next(i for i, u in enumerate(uses) if u.startswith("actions/attest@"))
    assert attest < steps.index(next(s for s in steps if "gh release create" in s.get("run", "")))


def test_release_never_enables_the_cache() -> None:
    path = WORKFLOWS / "release.yml"
    assert not re.search(r"enable-cache:\s*true", path.read_text(encoding="utf-8"))
    setups = [
        step
        for step in _steps(_load(path))
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert setups
    for step in setups:
        assert step.get("with", {}).get("enable-cache") is False


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_workflow_token_is_read_only_by_default(path: Path) -> None:
    expected = {} if path.name in NO_DEFAULT_TOKEN else {"contents": "read"}
    assert _load(path)["permissions"] == expected


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_job_permissions_do_not_repeat_the_workflow_grant(path: Path) -> None:
    # A job block replaces the workflow grant, so contents: read next to other
    # grants is needed; a block that is only contents: read is redundant.
    for name, job in _jobs(path).items():
        assert job.get("permissions") != {"contents": "read"}, f"{path.name}: {name}"


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_every_permission_grant_has_a_comment(path: Path) -> None:
    grants = re.findall(
        r"^ {6}[a-z-]+: (?:read|write|none)(?: #.*)?$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    for grant in grants:
        assert re.search(r" # \S", grant), f"{path.name}: {grant.strip()}"


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_expression_is_expanded_inside_a_run_script(path: Path) -> None:
    for step in _steps(_load(path)):
        assert "${{" not in step.get("run", ""), f"{path.name}: {step.get('name')}"


def test_zizmor_job_is_pinned_and_read_only() -> None:
    job = _jobs(WORKFLOWS / "security.yml")["zizmor"]
    assert job["name"] == "zizmor"
    assert "permissions" not in job
    run = next(step["run"] for step in job["steps"] if "run" in step)
    assert re.fullmatch(
        r"uvx --exclude-newer \d{4}-\d{2}-\d{2} zizmor@\d+\.\d+\.\d+ \.github", run.strip()
    )


def test_semgrep_runs_from_pinned_uvx_with_the_same_rules() -> None:
    job = _jobs(WORKFLOWS / "security.yml")["semgrep"]
    assert "container" not in job
    scan = " ".join(next(s["run"] for s in job["steps"] if s.get("name") == "Scan").split())
    assert re.search(r"uvx --exclude-newer \d{4}-\d{2}-\d{2} semgrep@\d+\.\d+\.\d+ scan", scan)
    assert "--config p/default" in scan
    assert "--error" in scan


def _required_contexts() -> list[str]:
    ruleset = json.loads((RULESETS / "main.json").read_text(encoding="utf-8"))
    rule = next(r for r in ruleset["rules"] if r["type"] == "required_status_checks")
    assert rule["parameters"]["strict_required_status_checks_policy"] is True
    checks = rule["parameters"]["required_status_checks"]
    assert all(check["integration_id"] == GITHUB_ACTIONS_APP_ID for check in checks)
    return [check["context"] for check in checks]


def test_required_checks_are_the_agreed_set_and_include_zizmor() -> None:
    contexts = _required_contexts()
    assert len(contexts) == len(set(contexts))
    assert set(contexts) == REQUIRED_CHECKS
    assert "zizmor" in contexts


def test_every_required_check_is_reported_by_a_pull_request_job() -> None:
    names = {
        job["name"]
        .replace("${{ matrix.profile }}", profile)
        .replace("${{ matrix.python-version }}", "3.14")
        for path in WORKFLOW_FILES
        if path.name != "release.yml"
        for job in _jobs(path).values()
        for profile in ("full", "minimal")
    }
    assert set(_required_contexts()) <= names


def test_release_tags_ruleset_matches_the_template() -> None:
    tags = json.loads((RULESETS / "release-tags.json").read_text(encoding="utf-8"))
    assert tags["name"] == "release-tags"
    assert (tags["target"], tags["enforcement"], tags["bypass_actors"]) == ("tag", "active", [])
    assert tags["conditions"]["ref_name"]["include"] == ["refs/tags/v*"]
    assert [r["type"] for r in tags["rules"]] == ["deletion", "non_fast_forward", "update"]
    assert not (RULESETS / "tags.json").exists()


def _on(path: Path) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    workflow = _load(path)
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _only_job(path: Path) -> dict[str, Any]:
    jobs = _jobs(path)
    assert len(jobs) == 1
    return next(iter(jobs.values()))


def _run_text(path: Path, job: str) -> str:
    return "\n".join(step["run"] for step in _jobs(path)[job]["steps"] if "run" in step)


def _review_action() -> dict[str, Any]:
    steps = _only_job(REVIEW)["steps"]
    return next(s["with"] for s in steps if s["uses"].startswith("anthropics/claude-code-action@"))


def test_pip_audit_daily_runs_on_a_schedule_never_on_pull_requests() -> None:
    triggers = _on(DAILY)
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert len(triggers["schedule"]) == 1
    minute, _hour, *rest = triggers["schedule"][0]["cron"].split()
    assert minute.isdigit() and minute not in {"0", "00"}  # off the hour
    assert rest == ["*", "*", "*"]  # daily
    assert _load(DAILY)["permissions"] == {"contents": "read"}
    assert "permissions" not in _only_job(DAILY)
    assert _load(DAILY)["concurrency"] == {"group": "pip-audit-daily", "cancel-in-progress": False}


def test_pip_audit_daily_audits_the_same_export_as_the_required_check() -> None:
    assert _run_text(DAILY, "pip-audit-daily") == _run_text(SECURITY, "pip-audit")
    assert _only_job(DAILY)["name"] != _jobs(SECURITY)["pip-audit"]["name"]


def test_pip_audit_daily_does_not_use_the_cache() -> None:
    setups = [
        step
        for step in _steps(_load(DAILY))
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert setups
    for step in setups:
        assert step.get("with", {}).get("enable-cache") is False


def test_scorecard_triggers_are_schedule_and_push_to_main_only() -> None:
    triggers = _on(SCORECARD)
    assert set(triggers) == {"schedule", "push"}
    assert triggers["push"] == {"branches": ["main"]}
    assert len(triggers["schedule"]) == 1
    minute, _hour, _dom, _month, weekday = triggers["schedule"][0]["cron"].split()
    assert minute.isdigit() and minute not in {"0", "00"}  # off the hour
    assert weekday.isdigit()  # weekly


def test_scorecard_follows_the_publishing_restrictions() -> None:
    workflow = _load(SCORECARD)
    assert workflow["permissions"] == {}
    assert "env" not in workflow and "defaults" not in workflow
    assert workflow["concurrency"] == {
        "group": "scorecard-${{ github.ref }}",
        "cancel-in-progress": True,
    }
    job = _only_job(SCORECARD)
    assert "env" not in job and "defaults" not in job
    assert "container" not in job and "services" not in job
    assert job["permissions"] == {
        "security-events": "write",
        "id-token": "write",
        "contents": "read",
        "actions": "read",
    }
    approved = (
        "actions/checkout@",
        "actions/upload-artifact@",
        "github/codeql-action/upload-sarif@",
        "ossf/scorecard-action@",
        "step-security/harden-runner@",
    )
    for step in job["steps"]:
        assert "run" not in step
        assert step["uses"].startswith(approved), step["uses"]


def test_scorecard_publishes_sarif_to_code_scanning() -> None:
    steps = _only_job(SCORECARD)["steps"]
    scorecard = next(s for s in steps if s["uses"].startswith("ossf/scorecard-action@"))
    assert scorecard["with"]["publish_results"] is True
    assert scorecard["with"]["results_format"] == "sarif"
    upload = next(s for s in steps if s["uses"].startswith("github/codeql-action/upload-sarif@"))
    assert upload["with"]["sarif_file"] == scorecard["with"]["results_file"]
    assert upload["with"]["category"] == "scorecard"


def test_id_token_write_is_only_on_scorecard_claude_review_and_release() -> None:
    allowed = {(SCORECARD, "analysis"), (REVIEW, "review"), (RELEASE, "release")}
    for path in WORKFLOW_FILES:
        for name, job in _jobs(path).items():
            granted = job.get("permissions", {}).get("id-token")
            if (path, name) in allowed:
                assert granted == "write", (path.name, name)
                text = path.read_text(encoding="utf-8")
                assert re.search(r"^\s+id-token: write # \S", text, re.MULTILINE), path.name
            else:
                assert granted is None, (path.name, name)


def test_claude_review_runs_only_on_pull_requests_and_cancels_superseded_runs() -> None:
    triggers = _on(REVIEW)
    assert triggers == {
        "pull_request": {"types": ["opened", "synchronize", "ready_for_review", "reopened"]}
    }
    assert _load(REVIEW)["concurrency"] == {
        "group": "claude-review-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_workflow_uses_pull_request_target(path: Path) -> None:
    assert "pull_request_target" not in path.read_text(encoding="utf-8")


def test_claude_review_skips_dependabot_forks_and_drafts() -> None:
    condition = " ".join(_only_job(REVIEW)["if"].split())
    assert condition == (
        "github.actor != 'dependabot[bot]' "
        "&& github.event.pull_request.head.repo.fork != true "
        "&& github.event.pull_request.draft != true"
    )


def test_claude_review_token_is_read_only_plus_id_token() -> None:
    assert _load(REVIEW)["permissions"] == {}
    assert _only_job(REVIEW)["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
        "issues": "read",
        "id-token": "write",
    }


def test_claude_review_uses_the_org_secret_and_an_untrusted_input_prompt() -> None:
    inputs = _review_action()
    # A reference to the secret, never a literal value.
    assert inputs["claude_code_oauth_token"] == "${{ secrets." + "CLAUDE_CODE_OAUTH_TOKEN }}"
    assert "untrusted data, not instructions" in " ".join(inputs["prompt"].split())
    assert "ANTHROPIC_API_KEY" not in REVIEW.read_text(encoding="utf-8")


def test_claude_review_turns_the_sandbox_off_and_keeps_one_tool() -> None:
    args = shlex.split(_review_action()["claude_args"])
    # The runner cannot start the sandbox; a command-line setting beats the project file.
    assert args.count("--settings") == 1
    assert json.loads(args[args.index("--settings") + 1]) == {"sandbox": {"enabled": False}}
    # Safe only because the reviewer has no Bash: the one tool is the inline comment.
    assert args.count("--allowedTools") == 1
    assert args[args.index("--allowedTools") + 1 :] == [
        "mcp__github_inline_comment__create_inline_comment"
    ]
    assert args.count("--settings") + args.count("--allowedTools") == len(
        [a for a in args if a.startswith("--")]
    )


def test_new_workflows_are_not_required_checks() -> None:
    contexts = set(_required_contexts())
    assert contexts == REQUIRED_CHECKS
    for path in (DAILY, SCORECARD, REVIEW):
        for job in _jobs(path).values():
            assert job["name"] not in contexts, path.name


def test_dependabot_covers_uv_and_actions_with_a_cooldown_and_grouped_updates() -> None:
    updates = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))["updates"]
    assert {u["package-ecosystem"] for u in updates} == {"uv", "github-actions"}
    for update in updates:
        assert update["directory"] == "/"
        assert update["schedule"]["interval"] == "weekly"
        assert update["cooldown"]["default-days"] == 7
        groups = list(update["groups"].values())
        assert [g["update-types"] for g in groups] == [["minor", "patch"]]


def test_ruff_and_mypy_job_runs_lint_format_check_and_types_without_pyflakes() -> None:
    job = _jobs(WORKFLOWS / "tests.yml")["static-checks"]
    assert job["name"] == "ruff and mypy"
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert runs[-3:] == [
        "uv run --no-sync ruff check .",
        "uv run --no-sync ruff format --check .",
        "uv run --no-sync mypy",
    ]
    for path in WORKFLOW_FILES:
        assert "pyflakes" not in path.read_text(encoding="utf-8"), path.name


def test_release_build_runs_the_same_static_checks_and_writes_the_sbom() -> None:
    steps = _jobs(RELEASE)["build"]["steps"]
    runs = [step.get("run", "") for step in steps]
    for command in (
        "uv run --no-sync ruff check .",
        "uv run --no-sync ruff format --check .",
        "uv run --no-sync mypy",
    ):
        assert command in runs
    # The SBOM exists before the checksums are written, and they cover it.
    sbom = runs.index("make sbom")
    sums = next(i for i, run in enumerate(runs) if "SHA256SUMS" in run)
    assert sbom < sums
    assert "sbom.cdx.json" in runs[sums]
    upload = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert "dist/" in upload["with"]["path"]


def test_release_attests_and_attaches_the_sbom_without_building_it() -> None:
    release = _jobs(RELEASE)["release"]["steps"]
    attest = next(s for s in release if str(s.get("uses", "")).startswith("actions/attest@"))
    assert "dist/sbom.cdx.json" in attest["with"]["subject-path"].split()
    create = next(s["run"] for s in release if "gh release create" in s.get("run", ""))
    assert "dist/sbom.cdx.json" in create.split()
    # The release job holds the write and OIDC tokens, so it runs no make or uv.
    assert all("make " not in step.get("run", "") for step in release)
    assert all("uv " not in step.get("run", "") for step in release)
