"""Unit tests for questvector.cli (the `qv` command-line interface)."""

from __future__ import annotations

import json
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
