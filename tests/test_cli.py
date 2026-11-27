"""Unit tests for questvector.cli (the `qv` command-line interface)."""

# ruff: noqa: RUF001
# The en dash is part of the resume date range under test.
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from export_text import docx_text, pdf_text

from questvector import __version__, cli
from questvector.core import vault


def test_version_flag_prints_version_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--version"])

    assert exc_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_installed_package_version_matches_dunder_version() -> None:
    # pyproject.toml sources its packaging version from questvector.__version__
    # (see [tool.setuptools.dynamic]) rather than duplicating the string --
    # this guards against the two silently drifting apart again.
    import importlib.metadata

    assert importlib.metadata.version("questvector") == __version__


def test_launch_creates_workspace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace_dir = tmp_path / "ws"
    exit_code = cli.main(["launch", "--dir", str(workspace_dir), "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["workspace_dir"] == str(workspace_dir)
    assert (workspace_dir / "Capabilities.md").exists()


def test_sync_ast_scores_job_description(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])
    (workspace_dir / "Capabilities.md").write_text(
        "## Cloud\n- AWS Terraform Kubernetes automation and CI/CD pipelines\n",
        encoding="utf-8",
    )
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("Looking for AWS Terraform Kubernetes CI/CD experience", encoding="utf-8")
    capsys.readouterr()

    exit_code = cli.main(
        [
            "sync-ast",
            "--dir",
            str(workspace_dir),
            "--target",
            str(jd_path),
            "--template",
            "devops-senior-mgr",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert 0.0 <= output["g_force_score"] <= 100.0
    assert "alert_level" in output


def test_sync_ast_unknown_template_returns_error_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("Some job description", encoding="utf-8")

    exit_code = cli.main(
        [
            "sync-ast",
            "--dir",
            str(workspace_dir),
            "--target",
            str(jd_path),
            "--template",
            "nonexistent",
        ]
    )

    assert exit_code == 1
    assert "ERROR" in capsys.readouterr().err


def test_export_produces_pdf_bundle(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])

    exit_code = cli.main(
        ["export", "--dir", str(workspace_dir), "--bundle", "my-resume", "--format", "pdf"]
    )

    assert exit_code == 0
    assert (workspace_dir / "bundles" / "my-resume.pdf").exists()


@pytest.mark.parametrize("name", ["../x", "a/b", "/abs/path", "", "a" * 65, ".", ".."])
def test_export_rejects_bad_bundle_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """R8: qv export refuses a bundle name that could leave bundles/."""
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])
    before = {p for p in tmp_path.rglob("*")}

    exit_code = cli.main(
        ["export", "--dir", str(workspace_dir), "--bundle", name, "--format", "pdf"]
    )

    assert exit_code == 1
    assert "Bundle name" in capsys.readouterr().err
    assert {p for p in tmp_path.rglob("*")} == before


def test_template_validate_fix_persists_and_returns_zero(tmp_path: Path) -> None:
    template_path = tmp_path / "bad.yaml"
    template_path.write_text(
        "categories:\n  - name: a\n    weight: 0.3\n  - name: b\n    weight: 0.3\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["template", "validate", str(template_path), "--fix"])

    assert exit_code == 0


def test_template_validate_without_fix_returns_one_when_invalid(tmp_path: Path) -> None:
    template_path = tmp_path / "bad.yaml"
    template_path.write_text(
        "categories:\n  - name: a\n    weight: 0.3\n  - name: b\n    weight: 0.3\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["template", "validate", str(template_path)])

    assert exit_code == 1


def test_launch_human_readable_output_lists_created_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    exit_code = cli.main(["launch", "--dir", str(workspace_dir)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Workspace initialized" in out
    assert "Capabilities.md" in out


def test_sync_ast_human_readable_output_shows_gaps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("Needs Kubernetes and Terraform at a senior level", encoding="utf-8")
    capsys.readouterr()

    exit_code = cli.main(
        [
            "sync-ast",
            "--dir",
            str(workspace_dir),
            "--target",
            str(jd_path),
            "--template",
            "devops-senior-mgr",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "G-Force Match" in out


def test_export_with_narrative_calls_llm_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])
    (workspace_dir / "Capabilities.md").write_text("## Cloud\n- AWS Terraform\n", encoding="utf-8")
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("Looking for AWS Terraform experience", encoding="utf-8")
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_a, **_k: "pass")
    vault.save_vault(
        workspace_dir / ".questvector.vault",
        "pass",
        vault.VaultData(llm_provider="anthropic", llm_api_keys={"anthropic": "sk-fake"}),
    )

    with patch("questvector.core.llm.AnthropicNarrativeGenerator") as mock_generator_cls:
        mock_generator_cls.return_value.generate.return_value = "Generated narrative text."
        exit_code = cli.main(
            [
                "export",
                "--dir",
                str(workspace_dir),
                "--bundle",
                "resume",
                "--format",
                "pdf",
                "--target",
                str(jd_path),
                "--template",
                "devops-senior-mgr",
                "--narrative",
            ]
        )

    assert exit_code == 0
    assert (workspace_dir / "bundles" / "resume.pdf").exists()


def _narrative_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, narrative: str, *extra: str
) -> Path:
    """Run ``qv export --narrative`` with a mocked provider returning ``narrative``."""
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])
    (workspace_dir / "Capabilities.md").write_text(
        "## Cloud\n- Ran AWS with Terraform and cut spend by 31%\n", encoding="utf-8"
    )
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("Looking for AWS Terraform experience", encoding="utf-8")
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_a, **_k: "pass")
    vault.save_vault(
        workspace_dir / ".questvector.vault",
        "pass",
        vault.VaultData(llm_provider="anthropic", llm_api_keys={"anthropic": "sk-fake"}),
    )
    with patch("questvector.core.llm.AnthropicNarrativeGenerator") as mock_generator_cls:
        mock_generator_cls.return_value.generate.return_value = narrative
        exit_code = cli.main(
            [
                "export",
                "--dir",
                str(workspace_dir),
                "--bundle",
                "out",
                "--format",
                "docx",
                "--target",
                str(jd_path),
                "--template",
                "devops-senior-mgr",
                "--narrative",
                *extra,
            ]
        )
    assert exit_code == 0
    return workspace_dir / "bundles" / "out.docx"


def test_export_strips_the_trailing_note_and_tells_the_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R14: the 5 Nov shape: the note never reaches the file, and the output says it was removed."""
    summary = "I ran AWS with Terraform and cut spend by 31%."
    note = "*Note: I did not claim Datadog, HashiCorp Vault or SOC 2.*"

    bundle = _narrative_export(tmp_path, monkeypatch, f"{summary}\n\n{note}")

    out = capsys.readouterr().out
    text = docx_text(bundle)
    assert summary in text
    assert "Datadog" not in text
    assert "HashiCorp" not in text
    assert "[QV] Removed from the summary (not exported): *Note: I did not claim Datadog" in out


def test_export_flags_are_printed_but_never_exported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R14: a flagged sentence still exports, the flag is printed, and the file has no flag text."""
    bundle = _narrative_export(tmp_path, monkeypatch, "I used Datadog for 7 years on AWS.")

    out = capsys.readouterr().out
    assert "[QV] Review: 7: number not in the dossier text" in out
    assert "Datadog: name or term not in the dossier text" in out
    text = docx_text(bundle)
    assert "I used Datadog for 7 years on AWS." in text
    assert "Review:" not in text
    assert "not in the dossier text" not in text


def test_export_json_carries_the_narrative_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R14: qv export --json reports the cleaned text, what was removed and the flags."""
    _narrative_export(
        tmp_path, monkeypatch, "I used Datadog on AWS.\n\nA second paragraph.", "--json"
    )

    out = capsys.readouterr().out
    payload = json.loads(out[out.index("{") :])
    assert payload["output_path"].endswith("out.docx")
    assert payload["narrative"]["text"] == "I used Datadog on AWS."
    assert payload["narrative"]["removed"] == ["A second paragraph."]
    assert [f["kind"] for f in payload["narrative"]["flags"]] == ["unsupported_term"]


def test_vault_set_key_stores_encrypted_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    # A new vault: passphrase, its confirmation, then the API key.
    responses = iter(["my-passphrase", "my-passphrase", "sk-my-api-key"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_args, **_kwargs: next(responses))

    exit_code = cli.main(
        ["vault", "set-key", "--dir", str(workspace_dir), "--provider", "anthropic"]
    )

    assert exit_code == 0
    loaded = vault.load_vault(workspace_dir / ".questvector.vault", "my-passphrase")
    assert loaded.llm_provider == "anthropic"
    assert loaded.api_key_for("anthropic") == "sk-my-api-key"


def test_vault_set_key_ollama_needs_no_api_key_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    # Only the vault passphrase and its confirmation (a new vault) should be
    # requested -- a third prompt would mean the CLI wrongly asked for an
    # API key Ollama doesn't need.
    prompts: list[str] = []

    def _getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return "my-passphrase"

    monkeypatch.setattr(cli.getpass, "getpass", _getpass)

    exit_code = cli.main(
        [
            "vault",
            "set-key",
            "--dir",
            str(workspace_dir),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
        ]
    )

    assert exit_code == 0
    assert prompts == ["Vault passphrase: ", "Confirm vault passphrase: "]
    loaded = vault.load_vault(workspace_dir / ".questvector.vault", "my-passphrase")
    assert loaded.llm_provider == "ollama"
    assert loaded.llm_model == "llama3.1"
    assert loaded.api_key_for("ollama") is None
    assert loaded.llm_timeout is None


def test_vault_set_key_stores_ollama_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_args, **_kwargs: "my-passphrase")

    exit_code = cli.main(
        [
            "vault",
            "set-key",
            "--dir",
            str(workspace_dir),
            "--provider",
            "ollama",
            "--timeout",
            "600",
        ]
    )

    assert exit_code == 0
    loaded = vault.load_vault(workspace_dir / ".questvector.vault", "my-passphrase")
    assert loaded.llm_timeout == 600


def test_vault_set_key_rejects_non_positive_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_args, **_kwargs: "my-passphrase")

    exit_code = cli.main(
        ["vault", "set-key", "--dir", str(workspace_dir), "--provider", "ollama", "--timeout", "0"]
    )

    assert exit_code == 1
    assert "--timeout must be a positive number" in capsys.readouterr().err
    assert not (workspace_dir / ".questvector.vault").exists()


def test_vault_set_key_new_vault_rejects_mismatched_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    # A third prompt (the API key) must never be reached.
    responses = iter(["my-passphrase", "my-passphrse"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_args, **_kwargs: next(responses))

    exit_code = cli.main(
        ["vault", "set-key", "--dir", str(workspace_dir), "--provider", "anthropic"]
    )

    assert exit_code == 1
    assert "Passphrases don't match; nothing was saved" in capsys.readouterr().err
    assert not (workspace_dir / ".questvector.vault").exists()


def test_vault_set_key_new_vault_rejects_empty_passphrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    responses = iter([""])
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_args, **_kwargs: next(responses))

    exit_code = cli.main(["vault", "set-key", "--dir", str(workspace_dir), "--provider", "ollama"])

    assert exit_code == 1
    assert "A new vault needs a non-empty passphrase" in capsys.readouterr().err
    assert not (workspace_dir / ".questvector.vault").exists()


def test_vault_set_key_existing_vault_asks_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    vault.save_vault(workspace_dir / ".questvector.vault", "my-passphrase", vault.VaultData())
    prompts: list[str] = []

    def _getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return "my-passphrase"

    monkeypatch.setattr(cli.getpass, "getpass", _getpass)

    exit_code = cli.main(["vault", "set-key", "--dir", str(workspace_dir), "--provider", "ollama"])

    assert exit_code == 0
    assert prompts == ["Vault passphrase: "]


def test_vault_set_key_existing_vault_with_empty_passphrase_still_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Vaults created before empty passphrases were refused must keep working.
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    vault.save_vault(workspace_dir / ".questvector.vault", "", vault.VaultData())
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_args, **_kwargs: "")

    exit_code = cli.main(["vault", "set-key", "--dir", str(workspace_dir), "--provider", "ollama"])

    assert exit_code == 0
    assert vault.load_vault(workspace_dir / ".questvector.vault", "").llm_provider == "ollama"


def test_vault_set_key_unknown_provider_rejected_by_argparse(tmp_path: Path) -> None:
    # --provider is constrained to PROVIDERS via argparse `choices`, so an
    # unknown value never reaches _cmd_vault_set_key's own guard clause.
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()

    with pytest.raises(SystemExit):
        cli.main(
            ["vault", "set-key", "--dir", str(workspace_dir), "--provider", "not-a-real-provider"]
        )


_NEGATION_DOSSIER = "## Cloud\n- AWS and Terraform automation\n- No hands-on Kubernetes\n"
_NEGATION_JD = "Needs AWS, Terraform and Kubernetes"


def _scored_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace_dir = tmp_path / "ws"
    cli.main(["launch", "--dir", str(workspace_dir)])
    (workspace_dir / "Capabilities.md").write_text(_NEGATION_DOSSIER, encoding="utf-8")
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text(_NEGATION_JD, encoding="utf-8")
    return workspace_dir, jd_path


def test_sync_ast_text_shows_counts_and_negation_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R3: the CLI shows asked counts, "not asked", and the negated lines (ASCII only)."""
    workspace_dir, jd_path = _scored_workspace(tmp_path)
    capsys.readouterr()

    cli.main(
        [
            *["sync-ast", "--dir", str(workspace_dir), "--target", str(jd_path)],
            *["--template", "devops-senior-mgr"],
        ]
    )

    out = capsys.readouterr().out
    assert "template keywords in this posting are in your dossier" in out
    assert "not asked (counts as full coverage)" in out
    assert " of " in out and " asked" in out
    assert 'Capabilities.md > Cloud: "No hands-on Kubernetes" (kubernetes)' in out
    assert out.isascii()


def test_sync_ast_json_keeps_existing_keys_and_adds_new_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R3: --json keeps every existing key and adds counts and warnings."""
    workspace_dir, jd_path = _scored_workspace(tmp_path)
    capsys.readouterr()

    cli.main(
        [
            *["sync-ast", "--dir", str(workspace_dir), "--target", str(jd_path)],
            *["--template", "devops-senior-mgr", "--json"],
        ]
    )

    output = json.loads(capsys.readouterr().out)
    existing = {
        "g_force_score",
        "alert_level",
        "gaps",
        "red_flags",
        "weak_categories",
        "categories",
    }
    assert existing <= output.keys()
    assert set(output) - existing == {
        "matched_count",
        "asked_count",
        "counts_text",
        "negation_warnings",
    }
    assert {"name", "weight", "coverage", "matched_keywords", "gap_keywords"} <= output[
        "categories"
    ][0].keys()
    assert output["negation_warnings"] == [
        {
            "file": "Capabilities.md",
            "heading": "Cloud",
            "line": "No hands-on Kubernetes",
            "keywords": ["kubernetes"],
        }
    ]
    assert output["matched_count"] <= output["asked_count"]


def test_export_from_the_cli_shows_counts_but_not_warnings(tmp_path: Path) -> None:
    """R8: the CLI's PDF and DOCX show the asked counts and never the negation warnings."""
    workspace_dir, jd_path = _scored_workspace(tmp_path)

    for fmt, read in (("pdf", pdf_text), ("docx", docx_text)):
        args = ["export", "--dir", str(workspace_dir), "--bundle", f"b-{fmt}", "--format", fmt]
        cli.main([*args, "--target", str(jd_path), "--template", "devops-senior-mgr"])
        text = read(workspace_dir / "bundles" / f"b-{fmt}.{fmt}")
        assert "template keywords in this posting are in your dossier" in text
        # PDF strings escape the parentheses, so check the two halves.
        assert "not asked" in text
        assert "counts as full coverage" in text
        assert "Check these lines" not in text


RESUME_FIXTURES = Path(__file__).parent / "fixtures" / "resume"
TODAY = date(2026, 11, 27)


@pytest.fixture()
def resume_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workspace holding the synthetic resume fixtures, with ``cli._today`` fixed."""
    workspace_dir = tmp_path / "ws"
    shutil.copytree(RESUME_FIXTURES, workspace_dir)
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    return workspace_dir


def resume_args(workspace_dir: Path, *extra: str, fmt: str = "docx") -> list[str]:
    return [
        "export",
        "--dir",
        str(workspace_dir),
        "--bundle",
        "cv",
        "--format",
        fmt,
        "--style",
        "resume",
        *extra,
    ]


def test_resume_export_writes_a_docx_without_a_cutoff_by_default(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R9: --style resume writes the resume; with no cutoff every role keeps its dates."""
    assert cli.main(resume_args(resume_workspace)) == 0

    text = docx_text(resume_workspace / "bundles" / "cv.docx")
    assert "Jordan Example" in text
    assert "Pinecrest Mills | Sep 2002" in text
    assert "Earlier Career" not in text
    assert "G-Force" not in text
    assert "[QV] Exported bundle:" in capsys.readouterr().out


def test_cutoff_years_without_a_value_means_20(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R9: a bare --cutoff-years is 20 years, and says what it moved and left out."""
    assert cli.main(resume_args(resume_workspace, "--cutoff-years")) == 0

    text = docx_text(resume_workspace / "bundles" / "cv.docx")
    assert "Earlier Career" in text
    assert "Pinecrest Mills | Sep 2002" not in text
    out = capsys.readouterr().out
    assert "[QV] Note: Moved 1 role(s) that ended before the cutoff to Earlier Career" in out
    assert "[QV] Note: Left out 1 line(s) that mention a year before 2006" in out


def test_cutoff_years_takes_a_value_and_refuses_a_role_that_straddles_it(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R9: --cutoff-years 15 puts the cutoff at Nov 2011; a role from 2008 to 2016 is refused."""
    assert cli.main(resume_args(resume_workspace, "--cutoff-years", "15")) == 1

    err = capsys.readouterr().err
    assert "Harbor Light Logistics (Jun 2008" in err
    assert "started before the cutoff year 2011" in err
    assert not (resume_workspace / "bundles" / "cv.docx").exists()


@pytest.mark.parametrize("value", ["0", "61", "-5", "abc", "1.5"])
def test_export_cutoff_years_values_outside_1_to_60_give_a_clear_error(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """R9: 0, 61, -5 and abc each stop with an error naming the option and the range."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(resume_args(resume_workspace, "--cutoff-years", value))

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--cutoff-years" in err
    assert "whole number of years from 1 to 60" in err


@pytest.mark.parametrize("style_args", [[], ["--style", "report"]])
def test_cutoff_years_without_the_resume_style_gives_a_clear_error(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str], style_args: list[str]
) -> None:
    """R9: --cutoff-years only means something for the resume style, and says so."""
    args = ["export", "--dir", str(resume_workspace), "--bundle", "cv", "--format", "docx"]

    assert cli.main([*args, *style_args, "--cutoff-years", "20"]) == 1
    assert "--cutoff-years needs --style resume" in capsys.readouterr().err
    assert not (resume_workspace / "bundles").exists()


def test_resume_without_contact_md_names_the_path(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R9: a missing Contact.md is one error naming the path it looked at."""
    (resume_workspace / "Contact.md").unlink()

    assert cli.main(resume_args(resume_workspace)) == 1
    assert str(resume_workspace / "Contact.md") in capsys.readouterr().err


def test_resume_with_old_style_headings_lists_them_and_the_form(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R9: the resume style names each heading that isn't in the role form; report still works."""
    (resume_workspace / "Chronology.md").write_text(
        "## Acme Corp — Senior SRE (2020-2023)\n- a\n", encoding="utf-8"
    )

    assert cli.main(resume_args(resume_workspace)) == 1
    err = capsys.readouterr().err
    assert '"Acme Corp — Senior SRE (2020-2023)"' in err
    assert "Title — Employer (Mon YYYY – Mon YYYY or Present)" in err
    report = ["export", "--dir", str(resume_workspace), "--bundle", "r", "--format", "pdf"]
    assert cli.main(report) == 0


def test_resume_pdf_reports_its_page_count_and_json_carries_it(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R9: a PDF resume prints its ReportLab page count; --json has style, notes and pages."""
    assert cli.main(resume_args(resume_workspace, fmt="pdf")) == 0
    assert "[QV] PDF pages: 1" in capsys.readouterr().out

    assert cli.main(resume_args(resume_workspace, "--cutoff-years", "20", "--json", fmt="pdf")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["style"] == "resume"
    assert payload["pdf_pages"] == 1
    assert payload["notes"][0].startswith("Moved 1 role(s)")


def test_contact_details_never_reach_the_narrative_prompt(
    resume_workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """R9: with --narrative, no Contact.md value is in the prompt, yet all are in the resume."""
    cli.main(["launch", "--dir", str(resume_workspace)])  # adds templates, keeps the files
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("Looking for AWS Terraform experience", encoding="utf-8")
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_a, **_k: "pass")
    vault.save_vault(
        resume_workspace / ".questvector.vault",
        "pass",
        vault.VaultData(llm_provider="anthropic", llm_api_keys={"anthropic": "sk-fake"}),
    )
    args = resume_args(
        resume_workspace, "--target", str(jd_path), "--template", "devops-senior-mgr", "--narrative"
    )

    with patch("questvector.core.llm.AnthropicNarrativeGenerator") as mock_generator_cls:
        generate = mock_generator_cls.return_value.generate
        generate.return_value = "I run platform teams on AWS."
        assert cli.main(args) == 0

    prompt = generate.call_args.args[0]
    values = [
        "Jordan",
        "Example",
        "jordan.example@example.com",
        "512 555 0100",
        "Austin",
        "linkedin.com",
        "github.com",
    ]
    assert not [v for v in values if v in prompt]
    text = docx_text(resume_workspace / "bundles" / "cv.docx")
    assert all(v in text for v in values)
    assert "I run platform teams on AWS." in text


def exported_docx(workspace_dir: Path, *extra: str) -> Path:
    assert cli.main(resume_args(workspace_dir, *extra)) == 0
    return workspace_dir / "bundles" / "cv.docx"


def test_check_export_passes_a_clean_resume_and_prints_the_verdict(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: qv check-export exits 0 on a clean resume and prints the length and the verdict."""
    path = exported_docx(resume_workspace)
    capsys.readouterr()

    assert cli.main(["check-export", str(path), "--dir", str(resume_workspace)]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Length: ")
    assert lines[-1] == "Check PASS: 0 problem(s), 0 warning(s)"


def test_check_export_exits_1_with_each_finding_on_its_own_line(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: a failing check exits 1 and prints one FAIL line per finding, naming the line."""
    path = exported_docx(resume_workspace)
    capsys.readouterr()

    code = cli.main(["check-export", str(path), "--dir", str(resume_workspace), "--cutoff-years"])

    assert code == 1
    out = capsys.readouterr().out.splitlines()
    year_lines = [line for line in out if line.startswith("FAIL year:")]
    assert len(year_lines) >= 2
    assert any("Pinecrest Mills | Sep 2002" in line for line in year_lines)
    assert out[-1].startswith("Check FAIL: ")


def test_check_export_json_has_the_report(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: qv check-export --json prints the report as JSON."""
    path = exported_docx(resume_workspace)
    capsys.readouterr()

    assert cli.main(["check-export", str(path), "--dir", str(resume_workspace), "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["passed"] is True and data["roles"] == 4 and data["findings"] == []


def test_check_export_without_contact_md_gives_one_error_naming_the_path(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: a missing Contact.md is one error naming the --dir path, not a list of failures."""
    path = exported_docx(resume_workspace)
    (resume_workspace / "Contact.md").unlink()
    capsys.readouterr()

    assert cli.main(["check-export", str(path), "--dir", str(resume_workspace)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert str(resume_workspace / "Contact.md") in captured.err
    assert "FAIL" not in captured.err


@pytest.mark.parametrize("value", ["0", "61", "-5", "abc"])
def test_check_export_cutoff_years_values_outside_1_to_60_give_a_clear_error(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """R10: 0, 61, -5 and abc each stop check-export with an error naming the option and range."""
    path = exported_docx(resume_workspace)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["check-export", str(path), "--cutoff-years", value])

    assert exc_info.value.code == 2
    assert "--cutoff-years: must be a whole number of years from 1 to 60" in capsys.readouterr().err


def test_check_export_reads_docx_files_only(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: a PDF is refused with a plain message saying where its page count comes from."""
    assert cli.main(resume_args(resume_workspace, fmt="pdf")) == 0

    code = cli.main(["check-export", str(resume_workspace / "bundles" / "cv.pdf")])

    assert code == 1
    assert "reads .docx files only" in capsys.readouterr().err


def test_resume_docx_export_runs_the_check_and_prints_it(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: a resume-style DOCX export checks the file it wrote and prints the verdict."""
    assert cli.main(resume_args(resume_workspace, "--cutoff-years")) == 0

    out = capsys.readouterr().out
    assert "[QV] Check PASS: 0 problem(s), 0 warning(s)" in out


def test_resume_docx_export_exits_1_when_the_check_fails_but_keeps_the_file(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: a failing check after export exits 1; the file stays and the failure is named."""
    (resume_workspace / "Chronology.md").write_text(
        "## Lead — Acme (Jan 2020 – Present)\n- Mentored her to promotion\n", encoding="utf-8"
    )

    assert cli.main(resume_args(resume_workspace)) == 1

    captured = capsys.readouterr()
    assert "[QV] FAIL pronoun: third-person her" in captured.out
    assert "The file was written, but the check failed." in captured.err
    assert (resume_workspace / "bundles" / "cv.docx").exists()


def test_resume_pdf_export_is_not_run_through_the_docx_check(
    resume_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R10: the check reads DOCX; a PDF export prints its page count and no check verdict."""
    assert cli.main(resume_args(resume_workspace, fmt="pdf")) == 0

    out = capsys.readouterr().out
    assert "PDF pages: 1" in out
    assert "Check " not in out
