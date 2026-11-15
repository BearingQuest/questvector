"""Every built requirement in docs/PRD.md is named in a test (REPO-07)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent

# "**R12 — Title.** **Built.**", "**Built** (date)" or "**Partly built.**"; Planned is skipped.
HEADING = re.compile(r"^\*\*(R\d+) — .*?\*\* \*\*(Built|Partly built)\b", re.MULTILINE)


def built_requirements() -> list[str]:
    text = (ROOT / "docs" / "PRD.md").read_text(encoding="utf-8")
    return [match.group(1) for match in HEADING.finditer(text)]


def test_prd_headings_are_still_parsed() -> None:
    # A heading-format change must not leave the guard with nothing to check.
    assert len(built_requirements()) >= 10


def test_every_built_requirement_is_named_in_a_test_docstring() -> None:
    docstrings = []
    for path in sorted(TESTS.glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
                "test_"
            ):
                docstrings.append(ast.get_docstring(node) or "")
    named = "\n".join(docstrings)
    missing = [rid for rid in built_requirements() if not re.search(rf"\b{rid}\b", named)]
    assert not missing, f"no test docstring names {', '.join(missing)}"
