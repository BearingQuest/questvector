"""The README Configuration table lists every setting, with its real default (DOC-06)."""

from __future__ import annotations

import ast
import re
from dataclasses import fields
from pathlib import Path

from questvector import config
from questvector.core import llm

ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()
ENV_NAME = re.compile(r"QV_[A-Z0-9_]+|[A-Z]+_API_KEY")


def readme_table() -> dict[str, str]:
    """Return {name: default} from the Configuration table in README.md."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## ⚙️ Configuration", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`") and cells[2].startswith("`"):
            rows[cells[0].strip("`")] = cells[2].strip("`")
    return rows


def config_settings() -> dict[str, str]:
    """Return {name: default as the README writes it} for config.py."""
    tree = ast.parse((ROOT / "questvector" / "config.py").read_text(encoding="utf-8"))
    names = [
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id.isupper()
    ]
    settings = {}
    for name in names:
        value = getattr(config, name)
        if name == "THEME":
            for field in fields(value):
                settings[f"THEME.{field.name}"] = getattr(value, field.name)
        elif name == "DEFAULT_CONFIG_DIR":
            settings[name] = str(value).replace(str(Path.home()), "~")
        elif name == "STOPWORDS":
            settings[name] = f"{len(value)} words"
        elif isinstance(value, tuple):
            settings[name] = ", ".join(value)
        else:
            settings[name] = value
    return settings


def env_settings() -> dict[str, str]:
    """Return {variable: default} for every variable the code or tests name."""
    found = set()
    sources = [*(ROOT / "questvector").rglob("*.py"), *(ROOT / "tests").glob("*.py")]
    for path in sources:
        if path.resolve() == THIS_FILE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and ENV_NAME.fullmatch(node.value)
            ):
                found.add(node.value)
    # test_remote_live builds QV_<PROVIDER>_MODEL with an f-string.
    found |= {f"QV_{pid.upper()}_MODEL" for pid, p in llm.PROVIDERS.items() if p.requires_api_key}
    defaults = {name: "unset" for name in found}
    for pid, provider in llm.PROVIDERS.items():
        if f"QV_{pid.upper()}_MODEL" in found:
            defaults[f"QV_{pid.upper()}_MODEL"] = provider.default_model
    defaults["QV_OLLAMA_HOST"] = llm.DEFAULT_OLLAMA_HOST
    defaults["QV_OLLAMA_TIMEOUT"] = llm.DEFAULT_OLLAMA_TIMEOUT
    return defaults


def same(readme_value: str, code_value: object) -> bool:
    if isinstance(code_value, float):
        try:
            return float(readme_value) == code_value
        except ValueError:
            return False
    return readme_value == str(code_value)


def test_the_table_is_still_parsed() -> None:
    # A format change must not leave the guard with nothing to check.
    assert len(readme_table()) >= 30


def test_every_setting_is_in_the_readme_table() -> None:
    table = readme_table()
    missing = sorted(({*config_settings(), *env_settings()}) - table.keys())
    assert not missing, f"README Configuration table is missing: {missing}"


def test_no_readme_row_names_a_setting_the_code_lacks() -> None:
    stale = sorted(readme_table().keys() - {*config_settings(), *env_settings()})
    assert not stale, f"README Configuration table lists settings not in the code: {stale}"


def test_readme_defaults_match_the_code() -> None:
    table = readme_table()
    wrong = {
        name: (table[name], code_value)
        for name, code_value in {**config_settings(), **env_settings()}.items()
        if name in table and not same(table[name], code_value)
    }
    assert not wrong, f"README default differs from the code (README, code): {wrong}"
