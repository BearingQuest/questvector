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
    "mypy and pyflakes",
    "Validate mission templates",
    "gitleaks",
    "semgrep",
    "pip-audit",
    "zizmor",
}
WORKFLOW_FILES = sorted(WORKFLOWS.glob("*.yml"))
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
    assert _load(path)["permissions"] == {"contents": "read"}


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
        job["name"].replace("${{ matrix.profile }}", profile).replace(
            "${{ matrix.python-version }}", "3.14"
        )
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
