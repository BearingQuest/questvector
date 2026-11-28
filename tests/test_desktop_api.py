"""Unit tests for questvector.desktop.app.Api.

These exercise the JS/Python bridge logic directly -- no pywebview runtime,
window, or display server is created or required.
"""

# ruff: noqa: RUF001
# The en dash is part of the resume date range under test.
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from export_text import pdf_text

from questvector import cli
from questvector.core import vault
from questvector.desktop.app import Api


def test_launch_workspace_returns_ok_envelope(tmp_path: Path) -> None:
    """R18: a bridge method answers with an ok envelope."""
    api = Api()
    response = api.launch_workspace(str(tmp_path / "ws"))
    assert response["ok"] is True
    assert "workspace_dir" in response["data"]


def test_launch_workspace_returns_error_envelope_on_failure(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-dir"
    file_path.write_text("x", encoding="utf-8")

    api = Api()
    response = api.launch_workspace(str(file_path))

    assert response["ok"] is False
    assert "error" in response


def test_get_dossier_returns_parsed_sections(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))
    (workspace_dir / "Capabilities.md").write_text("## Cloud\n- AWS\n", encoding="utf-8")

    response = api.get_dossier(str(workspace_dir))

    assert response["ok"] is True
    assert response["data"]["capabilities"] == [{"domain": "Cloud", "text": "AWS"}]


def test_list_templates_returns_seven_starter_templates(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))

    response = api.list_templates(str(workspace_dir))

    assert response["ok"] is True
    assert len(response["data"]) == 7


def test_sync_ast_returns_match_result(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))
    (workspace_dir / "Capabilities.md").write_text(
        "## Cloud\n- AWS Terraform Kubernetes CI/CD\n", encoding="utf-8"
    )

    response = api.sync_ast(
        str(workspace_dir), "Looking for AWS Terraform Kubernetes", "devops-senior-mgr"
    )

    assert response["ok"] is True
    assert "g_force_score" in response["data"]


def test_sync_ast_unknown_template_returns_error_envelope(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))

    response = api.sync_ast(str(workspace_dir), "Some JD text", "does-not-exist")

    assert response["ok"] is False


def test_validate_template_returns_result_dict(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    path.write_text("categories:\n  - name: a\n    weight: 1.0\n", encoding="utf-8")

    api = Api()
    response = api.validate_template(str(path), False)

    assert response["ok"] is True
    assert response["data"]["valid"] is True


def test_export_bundle_writes_file(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))

    response = api.export_bundle(str(workspace_dir), "resume", "pdf")

    assert response["ok"] is True
    assert Path(response["data"]["output_path"]).exists()


def test_set_llm_key_and_generate_narrative_error_without_key(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))

    set_response = api.set_llm_key(str(workspace_dir), "pass", "anthropic", "")
    assert set_response["ok"] is True

    narrative_response = api.generate_narrative(str(workspace_dir), "some jd text", "pass")
    # A provider was stored but no real API key, so this must fail
    # gracefully, not crash.
    assert narrative_response["ok"] is False


def test_set_llm_key_unknown_provider_returns_error_envelope(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))

    response = api.set_llm_key(str(workspace_dir), "pass", "not-a-real-provider", "some-key")

    assert response["ok"] is False


def test_set_llm_key_ollama_needs_no_api_key(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))

    response = api.set_llm_key(str(workspace_dir), "pass", "ollama", "", "llama3.1")

    assert response["ok"] is True
    loaded = vault.load_vault(workspace_dir / ".questvector.vault", "pass")
    assert loaded.llm_provider == "ollama"
    assert loaded.llm_model == "llama3.1"
    assert loaded.api_key_for("ollama") is None


def test_generate_narrative_success_with_mocked_llm(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))
    vault.save_vault(
        workspace_dir / ".questvector.vault",
        "pass",
        vault.VaultData(llm_provider="anthropic", llm_api_keys={"anthropic": "sk-fake"}),
    )

    with patch("questvector.core.llm.AnthropicNarrativeGenerator") as mock_generator_cls:
        mock_generator_cls.return_value.generate.return_value = "Generated summary."
        response = api.generate_narrative(str(workspace_dir), "some jd text", "pass")

    assert response["ok"] is True
    assert response["data"]["narrative"] == "Generated summary."


def test_generate_narrative_strips_and_flags_in_the_result(tmp_path: Path) -> None:
    """R14: the desktop result holds the cleaned text, what was removed and the flags."""
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))
    (workspace_dir / "Capabilities.md").write_text("## Cloud\n- Ran AWS\n", encoding="utf-8")
    vault.save_vault(
        workspace_dir / ".questvector.vault",
        "pass",
        vault.VaultData(llm_provider="anthropic", llm_api_keys={"anthropic": "sk-fake"}),
    )

    with patch("questvector.core.llm.AnthropicNarrativeGenerator") as mock_generator_cls:
        mock_generator_cls.return_value.generate.return_value = (
            "I ran AWS and Datadog.\n\n*Note: no SOC 2.*"
        )
        response = api.generate_narrative(str(workspace_dir), "some jd text", "pass")

    assert response["ok"] is True
    data = response["data"]
    assert data["narrative"] == "I ran AWS and Datadog."
    assert data["removed"] == ["*Note: no SOC 2.*"]
    assert [(f["kind"], f["terms"]) for f in data["flags"]] == [("unsupported_term", ["Datadog"])]


def test_generate_narrative_ollama_timeout_returns_error_instead_of_raising(tmp_path: Path) -> None:
    # A slow local model used to raise a raw TimeoutError through the bridge.
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))
    vault.save_vault(
        workspace_dir / ".questvector.vault",
        "pass",
        vault.VaultData(llm_provider="ollama", llm_model="llama3.1", llm_timeout=5.0),
    )

    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")) as mock_urlopen:
        response = api.generate_narrative(str(workspace_dir), "some jd text", "pass")

    assert response["ok"] is False
    assert "didn't finish within its 5-second limit" in response["error"]
    assert mock_urlopen.call_args.kwargs["timeout"] == 5.0


def test_list_llm_providers_includes_all_four() -> None:
    api = Api()
    response = api.list_llm_providers()

    assert response["ok"] is True
    ids = {provider["id"] for provider in response["data"]["providers"]}
    assert ids == {"anthropic", "openai", "gemini", "ollama"}
    ollama = next(p for p in response["data"]["providers"] if p["id"] == "ollama")
    assert ollama["is_local"] is True
    assert ollama["requires_api_key"] is False


def test_export_bundle_rejects_bad_names_and_writes_nothing_outside(tmp_path: Path) -> None:
    """R8, R18: a bad bundle name gets the error envelope and no file is written."""
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))
    before = {p for p in tmp_path.rglob("*")}

    for name in ["../x", "a/b", str(tmp_path / "abs"), "", "a" * 65, ".", ".."]:
        response = api.export_bundle(str(workspace_dir), name, "pdf")
        assert response["ok"] is False
        assert "Bundle name" in response["error"]

    assert {p for p in tmp_path.rglob("*")} == before


def _negated_workspace(tmp_path: Path) -> Path:
    workspace_dir = tmp_path / "ws"
    Api().launch_workspace(str(workspace_dir))
    (workspace_dir / "Capabilities.md").write_text(
        "## Cloud\n- AWS and Terraform automation\n- No hands-on Kubernetes\n", encoding="utf-8"
    )
    return workspace_dir


def test_sync_ast_matches_the_cli_json_and_includes_weak_categories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R3: the bridge and `qv sync-ast --json` give one dict, with weak categories."""
    workspace_dir = _negated_workspace(tmp_path)
    jd_text = "Needs AWS, Terraform and Kubernetes"
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text(jd_text, encoding="utf-8")
    argv = ["sync-ast", "--dir", str(workspace_dir), "--target", str(jd_path)]
    cli.main([*argv, "--template", "devops-senior-mgr", "--json"])
    cli_dict = json.loads(capsys.readouterr().out)

    response = Api().sync_ast(str(workspace_dir), jd_text, "devops-senior-mgr")

    assert response["ok"] is True
    assert response["data"] == cli_dict
    assert "weak_categories" in response["data"]
    assert response["data"]["negation_warnings"][0]["keywords"] == ["kubernetes"]
    assert all(c["counts_text"] for c in response["data"]["categories"])


def test_export_bundle_from_the_desktop_shows_counts_but_not_warnings(tmp_path: Path) -> None:
    """R8: a PDF exported from the window shows the asked counts and never the warnings."""
    workspace_dir = _negated_workspace(tmp_path)

    response = Api().export_bundle(
        str(workspace_dir),
        "scan",
        "pdf",
        "Needs AWS, Terraform and Kubernetes",
        "devops-senior-mgr",
    )

    assert response["ok"] is True
    text = pdf_text(Path(response["data"]["output_path"]))
    assert "template keywords in this posting are in your dossier" in text
    assert "No hands-on Kubernetes" in text  # the dossier body is exported as written
    assert "Check these lines" not in text
    assert "negat" not in text.lower()


def resume_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Api, Path]:
    import shutil
    from datetime import date

    from questvector.desktop import app

    workspace_dir = tmp_path / "ws"
    shutil.copytree(Path(__file__).parent / "fixtures" / "resume", workspace_dir)
    monkeypatch.setattr(app, "_today", lambda: date(2026, 11, 27))
    return Api(), workspace_dir


def test_export_bundle_resume_style_writes_a_resume_and_reports_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9: the bridge's resume style writes the resume, with the cutoff and what it moved."""
    api, workspace_dir = resume_api(tmp_path, monkeypatch)

    response = api.export_bundle(str(workspace_dir), "cv", "pdf", None, None, "resume", 20)

    assert response["ok"] is True
    data = response["data"]
    assert data["style"] == "resume" and data["pdf_pages"] == 1
    assert data["notes"][0].startswith("Moved 1 role(s)")
    assert Path(data["output_path"]).read_bytes()[:5] == b"%PDF-"


def test_export_bundle_resume_style_errors_come_back_as_envelopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9: a missing Contact.md, a bad cutoff, a cutoff without the resume style or an unknown
    style each return an error envelope and write nothing."""
    api, workspace_dir = resume_api(tmp_path, monkeypatch)
    directory = str(workspace_dir)

    assert (
        "from 1 to 60"
        in api.export_bundle(directory, "cv", "docx", None, None, "resume", 0)["error"]
    )
    assert (
        "needs the resume style"
        in api.export_bundle(directory, "cv", "docx", None, None, "report", 20)["error"]
    )
    assert (
        "Unknown export style"
        in api.export_bundle(directory, "cv", "docx", None, None, "cv")["error"]
    )
    (workspace_dir / "Contact.md").unlink()
    missing = api.export_bundle(directory, "cv", "docx", None, None, "resume")
    assert missing["ok"] is False and str(workspace_dir / "Contact.md") in missing["error"]
    assert not (workspace_dir / "bundles").exists()


def test_export_bundle_defaults_to_the_report_style(tmp_path: Path) -> None:
    """R9: without a style the bridge exports the report, as before."""
    workspace_dir = tmp_path / "ws"
    api = Api()
    api.launch_workspace(str(workspace_dir))

    response = api.export_bundle(str(workspace_dir), "bundle", "docx")

    assert response["ok"] is True
    assert response["data"] == {"output_path": str(workspace_dir / "bundles" / "bundle.docx")}


def test_export_bundle_resume_docx_includes_the_file_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10: a resume DOCX export from the window returns the check, failing or not."""
    api, workspace_dir = resume_api(tmp_path, monkeypatch)

    clean = api.export_bundle(str(workspace_dir), "cv", "docx", None, None, "resume", 20)

    assert clean["ok"] is True
    assert clean["data"]["check"]["passed"] is True
    assert clean["data"]["check"]["lines"][-1] == "Check PASS: 0 problem(s), 0 warning(s)"

    (workspace_dir / "Chronology.md").write_text(
        "## Lead — Acme (Jan 2020 – Present)\n- Mentored her to promotion\n", encoding="utf-8"
    )
    failing = api.export_bundle(str(workspace_dir), "cv2", "docx", None, None, "resume")

    assert failing["ok"] is True  # the file was written
    assert failing["data"]["check"]["passed"] is False
    assert Path(failing["data"]["output_path"]).exists()

    pdf = api.export_bundle(str(workspace_dir), "cv3", "pdf", None, None, "resume")
    assert pdf["data"]["check"] is None


def test_sync_ast_returns_the_relevance_keys(tmp_path: Path) -> None:
    """R3 (ADR-0033): the bridge returns coverage, relevance and the low-relevance level."""
    workspace_dir = _negated_workspace(tmp_path)

    response = Api().sync_ast(str(workspace_dir), "Needs AWS and Terraform", "devops-senior-mgr")
    data = response["data"]

    assert data["alert_level"] == "low_relevance"
    assert data["low_relevance"] is True
    assert (data["asked_template_count"], data["template_keyword_count"]) == (2, 36)
    assert data["relevance"] == 5.6
    assert data["relevance_text"] == "2 of 36 template keywords (6%)"
    assert "little of this template" in data["relevance_note"]
    assert data["coverage"] == data["g_force_score"]


def test_sync_ast_with_nothing_asked_has_no_coverage_number(tmp_path: Path) -> None:
    """R3 (ADR-0033): nothing asked: coverage is null and the text says nothing was found."""
    workspace_dir = _negated_workspace(tmp_path)

    data = Api().sync_ast(str(workspace_dir), "Needs welding", "devops-senior-mgr")["data"]

    assert data["coverage"] is None
    assert data["alert_level"] == "low_relevance"
    assert data["coverage_text"] == "no template keywords found in this posting"
    assert "no template keywords found" in data["relevance_note"].lower()
    assert "100%" not in data["coverage_text"] + data["relevance_note"]


def test_sync_ast_low_relevance_data_has_no_score_percentage(tmp_path: Path) -> None:
    """R3 (ADR-0033): what the window shows for a low-relevance result carries no percentage.

    The window reads `coverage_text`, `category_coverage_texts` and, for the gauge,
    `low_relevance` (it shows "--"); `coverage` itself stays in the data.
    """
    workspace_dir = _negated_workspace(tmp_path)

    data = Api().sync_ast(str(workspace_dir), "Needs AWS and Terraform", "devops-senior-mgr")[
        "data"
    ]

    assert data["low_relevance"] is True
    assert data["coverage"] == 100.0
    assert data["coverage_text"] == "not scored (low relevance)"
    assert set(data["category_coverage_texts"]) == {"-"}
    assert "%" not in data["coverage_text"] + "".join(data["category_coverage_texts"])
