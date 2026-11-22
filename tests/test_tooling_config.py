"""The lint, type-check and ignore-file settings the baseline requires (ADR-0023)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
RULE_SET = {"E", "F", "W", "I", "B", "UP", "S", "SIM", "RUF", "T20"}


def pyproject() -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data


def test_ruff_matches_the_baseline_block() -> None:
    ruff = pyproject()["tool"]["ruff"]
    assert ruff["line-length"] == 100
    assert ruff["target-version"] == "py314"
    assert ruff["extend-exclude"] == ["spikes"]
    assert set(ruff["lint"]["select"]) == RULE_SET
    assert ruff["lint"]["per-file-ignores"] == {
        "tests/**": ["S101"],
        "questvector/cli.py": ["T201"],
        "tests/live_narrative.py": ["T201"],
    }


def test_ruff_is_pinned_in_the_dev_group_and_pyflakes_is_gone() -> None:
    dev = pyproject()["dependency-groups"]["dev"]
    assert any(re.fullmatch(r"ruff==\d+\.\d+\.\d+", pin) for pin in dev)
    assert not any(pin.lower().startswith("pyflakes") for pin in dev)


def test_mypy_is_strict_for_the_whole_package_with_no_overrides() -> None:
    mypy = pyproject()["tool"]["mypy"]
    assert mypy["strict"] is True
    assert mypy["files"] == ["questvector"]
    assert "overrides" not in mypy


def test_blame_ignore_file_lists_only_full_commit_hashes() -> None:
    lines = (ROOT / ".git-blame-ignore-revs").read_text(encoding="utf-8").splitlines()
    revs = [line for line in lines if line and not line.startswith("#")]
    assert "f19c6914728211163612037fca4a214dc2c1c4be" in revs
    for rev in revs:
        assert re.fullmatch(r"[0-9a-f]{40}", rev), rev


def test_gitignore_covers_the_tool_caches_and_local_files() -> None:
    entries = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    expected = {
        ".ruff_cache/",
        ".mypy_cache/",
        ".pytest_cache/",
        ".coverage",
        "dist/",
        "audit-requirements.txt",
        ".env*",
        ".claude/settings.local.json",
        ".DS_Store",
        "*.tfstate",
        "*.tfstate.*",
        ".terraform/",
    }
    assert expected <= entries


def test_no_noqa_line_length_exemption_in_the_package() -> None:
    for path in sorted((ROOT / "questvector").rglob("*.py")):
        assert "noqa: E501" not in path.read_text(encoding="utf-8"), path.name


def test_records_are_kept_current() -> None:
    """R21: the changelog has an Unreleased section and every ADR is in the index."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    index = (ROOT / "docs" / "decisions" / "README.md").read_text(encoding="utf-8")
    for record in sorted((ROOT / "docs" / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md")):
        if record.name.startswith("0000-"):
            continue
        assert record.name in index, record.name


def test_makefile_has_the_five_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert ".PHONY: help check audit sbom hooks" in makefile
    for target in ("help", "check", "audit", "sbom", "hooks"):
        assert re.search(rf"^{target}:", makefile, re.MULTILINE), target


def test_tests_start_processes_only_through_proc_py() -> None:
    starters = re.compile(
        r"subprocess\.(run|Popen|call|check_call|check_output)|os\.(system|popen)"
    )
    for path in sorted(TESTS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name in {"_proc.py", Path(__file__).name}:
            continue
        assert not starters.search(text), f"{path.name} starts a process; use _proc.run"


def test_proc_py_holds_the_only_s603_noqa() -> None:
    holders = [
        path.name
        for path in sorted(TESTS.glob("*.py"))
        if "noqa: S603" in path.read_text(encoding="utf-8") and path.name != Path(__file__).name
    ]
    assert holders == ["_proc.py"]


def _tool_uv_lines() -> list[str]:
    lines = (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    return lines[lines.index("[tool.uv]") + 1 :]


def test_exclude_newer_is_the_first_key_under_tool_uv() -> None:
    # Semgrep reads the table only up to the first bracket, so nothing with a
    # bracket may sit between the header and this key (ADR-0026).
    keys = [line for line in _tool_uv_lines() if re.match(r"[A-Za-z_-]+\s*=", line)]
    assert keys[0] == 'exclude-newer = "7 days"'
    above = _tool_uv_lines()[: _tool_uv_lines().index(keys[0])]
    assert not any("[" in line or "]" in line for line in above)


def test_lock_records_the_seven_day_span() -> None:
    assert 'exclude-newer-span = "P7D"' in (ROOT / "uv.lock").read_text(encoding="utf-8")
