"""``qv`` command-line interface.

Spec reference: MASTER_DEVELOPER_SPEC.pdf Section 3 defines the CLI surface.
Built with :mod:`argparse` (Standard Library) rather than a third-party CLI
framework, per this project's "stdlib before third-party" standard.

Commands
    qv launch [--dir PATH]
        Initialize a local career dossier workspace with starter templates.
    qv sync-ast --target JD_FILE --template TEMPLATE_ID [--dir PATH] [--json]
        Parse a job description, run the Micro-Diff Matching Engine against
        the workspace dossier, and print the G-Force match score.
    qv export --bundle NAME --format {pdf,docx} [--dir PATH]
               [--target JD_FILE --template TEMPLATE_ID] [--narrative]
               [--style {report,resume}] [--cutoff-years [N]] [--json]
        Compile the dossier (optionally with a match summary and an
        LLM-generated narrative) into a PDF or DOCX bundle. A generated
        narrative is checked first: extras are stripped and doubtful
        sentences are listed (never blocked).
    qv template validate PATH [--fix] [--json]
        Lint a mission template YAML file; with --fix, rescale weights to
        sum to 1.00 and persist the fix.
    qv vault set-key --provider {anthropic,openai,gemini,ollama} [--dir PATH]
                     [--model NAME] [--host URL]
        Store an LLM provider selection (and, for cloud providers, an API
        key) in the workspace's encrypted vault. This command is an
        addition beyond the original spec's CLI table, necessary to make
        narrative generation (Stage 1 blueprint decision) usable at all
        without a plaintext key on disk.
    qv --version
        Print the installed QuestVector version (from
        ``questvector.__version__``, the single source of truth also used
        by ``pyproject.toml``'s packaging metadata -- see that file's
        ``[tool.setuptools.dynamic]`` section).
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from questvector import __version__
from questvector.config import CONTACT_FILENAME
from questvector.core import matcher, templates, workspace
from questvector.core.contact import parse_contact
from questvector.core.exporter import export_bundle, export_resume, resolve_bundle_path
from questvector.core.guardrails import NarrativeCheck, check_narrative
from questvector.core.llm import (
    PROVIDERS,
    build_narrative_prompt,
    create_narrative_generator,
    dossier_context_for_prompt,
)
from questvector.core.markdown_parser import ROLE_HEADING_EXAMPLE, parse_dossier
from questvector.core.models import MissionTemplate
from questvector.core.resume import (
    DEFAULT_CUTOFF_YEARS,
    MAX_CUTOFF_YEARS,
    MIN_CUTOFF_YEARS,
    build_resume,
    validate_cutoff_years,
)
from questvector.core.vault import VaultData, load_vault, update_vault
from questvector.exceptions import ExportError, LLMError, QuestVectorError, VaultError

_VAULT_FILENAME = ".questvector.vault"


def _today() -> date:
    """Return today's date. The one place the CLI reads the clock; tests replace it."""
    return date.today()


def _cutoff_years_arg(value: str) -> int:
    """Parse a ``--cutoff-years`` value for argparse (whole years, 1 to 60)."""
    try:
        return validate_cutoff_years(int(value))
    except ValueError, ExportError:
        raise argparse.ArgumentTypeError(
            f"must be a whole number of years from {MIN_CUTOFF_YEARS} to {MAX_CUTOFF_YEARS}, "
            f"got {value!r}"
        ) from None


def _resolve_workspace_dir(raw: str | None) -> Path:
    """Resolve the ``--dir`` argument to an absolute workspace path.

    Args:
        raw: The raw ``--dir`` value, or ``None`` to use the current
            working directory.

    Returns:
        An absolute :class:`Path`.
    """
    return Path(raw).expanduser().resolve() if raw else Path.cwd()


def _template_search_dirs(workspace_dir: Path) -> list[Path]:
    """Return the ordered list of directories a workspace searches for templates.

    Args:
        workspace_dir: The workspace directory.

    Returns:
        ``templates/starter`` (built-in, spec Section 4), then
        ``templates/community`` (contributions per ``CONTRIBUTING_TEMPLATES.md``),
        then ``templates/`` itself as a final fallback.
    """
    return [
        workspace_dir / "templates" / "starter",
        workspace_dir / "templates" / "community",
        workspace_dir / "templates",
    ]


def _find_template(workspace_dir: Path, template_id: str) -> MissionTemplate:
    """Locate and load a mission template by id from a workspace.

    Args:
        workspace_dir: The workspace directory to search.
        template_id: The template's mission id (filename stem, minus any
            ``.qv-mission`` extension).

    Returns:
        The loaded :class:`MissionTemplate`.

    Raises:
        QuestVectorError: If no matching template file is found.
    """
    search_dirs = _template_search_dirs(workspace_dir)
    match = templates.find_template_file(search_dirs, template_id)
    if match is not None:
        return templates.load_template(match)

    available = sorted(
        {
            templates.template_id_from_filename(path.name)
            for directory in search_dirs
            for path in templates.list_template_files(directory)
        }
    )
    raise QuestVectorError(
        f"No mission template found with id '{template_id}'",
        context={"searched": [str(d) for d in search_dirs], "available": available},
    )


def _cmd_launch(args: argparse.Namespace) -> int:
    """Handle ``qv launch``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code.
    """
    workspace_dir = _resolve_workspace_dir(args.dir)
    result = workspace.init_workspace(workspace_dir)
    if args.json:
        print(
            json.dumps(
                {
                    "workspace_dir": str(result.workspace_dir),
                    "created_files": [str(p) for p in result.created_files],
                    "skipped_files": [str(p) for p in result.skipped_files],
                }
            )
        )
    else:
        print(f"[QV] Workspace initialized: {result.workspace_dir}")
        for path in result.created_files:
            print(f"  + {path.relative_to(result.workspace_dir)}")
        for path in result.skipped_files:
            print(f"  = {path.relative_to(result.workspace_dir)} (already existed, left untouched)")
    return 0


def _cmd_sync_ast(args: argparse.Namespace) -> int:
    """Handle ``qv sync-ast``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code.
    """
    workspace_dir = _resolve_workspace_dir(args.dir)
    dossier = parse_dossier(workspace_dir)
    jd_text = Path(args.target).expanduser().read_text(encoding="utf-8")
    job_description = matcher.parse_job_description(jd_text, source=args.target)
    template = _find_template(workspace_dir, args.template)
    result = matcher.run_match(dossier, job_description, template)

    if args.json:
        print(json.dumps(result.to_dict()))
    else:
        print(
            f"[QV] G-Force Match: {result.g_force_score:.1f}%  ({result.alert_level.value.upper()})"
        )
        print(f"[QV] {result.counts_text()}")
        for category in result.category_scores:
            print(
                f"  - {category.name}: {category.coverage * 100:.0f}% coverage "
                f"(weight {category.weight:.2f}), {category.counts_text()}"
            )
        if result.gaps:
            print(f"[QV] Gaps: {', '.join(result.gaps)}")
        if result.weak_categories:
            print(f"[QV] Weak categories: {', '.join(result.weak_categories)}")
        if result.red_flags:
            print(f"[QV] RED FLAGS: {'; '.join(result.red_flags)}")
        if result.negation_warnings:
            print("[QV] Check these lines (a negated skill still counts toward the score):")
            for warning in result.negation_warnings:
                print(
                    f'  - {warning.file} > {warning.heading}: "{warning.line}" '
                    f"({', '.join(warning.keywords)})"
                )
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Handle ``qv export``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code.
    """
    workspace_dir = _resolve_workspace_dir(args.dir)
    # Checked first: a bad name must fail before any narrative network call.
    output_dir = workspace_dir / "bundles"
    output_path = resolve_bundle_path(output_dir, args.bundle, args.format)
    resume_style = args.style == "resume"
    if args.cutoff_years is not None and not resume_style:
        raise QuestVectorError("--cutoff-years needs --style resume")
    dossier = parse_dossier(workspace_dir, require_roles=resume_style)
    today = _today()
    contact = None
    if resume_style:
        contact = parse_contact(workspace_dir / CONTACT_FILENAME)
        # Fail on a role that conflicts with the cutoff before any narrative network call.
        build_resume(dossier, contact, narrative=None, cutoff_years=args.cutoff_years, today=today)

    match_result = None
    if args.target and args.template:
        jd_text = Path(args.target).expanduser().read_text(encoding="utf-8")
        job_description = matcher.parse_job_description(jd_text, source=args.target)
        template = _find_template(workspace_dir, args.template)
        match_result = matcher.run_match(dossier, job_description, template)

    narrative = None
    narrative_check: NarrativeCheck | None = None
    if args.narrative:
        if match_result is None:
            raise QuestVectorError("--narrative requires both --target and --template to be set")
        passphrase = getpass.getpass("Vault passphrase: ")
        vault_path = workspace_dir / _VAULT_FILENAME
        vault_data = load_vault(vault_path, passphrase)
        if not vault_data.llm_provider:
            raise LLMError(
                "No LLM provider configured yet -- run 'qv vault set-key --provider <name>' first"
            )
        generator = create_narrative_generator(
            vault_data.llm_provider,
            api_key=vault_data.api_key_for(vault_data.llm_provider),
            model=vault_data.llm_model,
            host=vault_data.llm_host,
            timeout=vault_data.llm_timeout,
        )
        dossier_context = dossier_context_for_prompt(dossier)
        prompt = build_narrative_prompt(
            dossier_context, job_description.raw_text, tone_style=template.tone_style
        )
        narrative_check = check_narrative(generator.generate(prompt), dossier_context)
        narrative = narrative_check.text

    output_dir.mkdir(parents=True, exist_ok=True)
    notes: tuple[str, ...] = ()
    pdf_pages: int | None = None
    if contact is not None:
        result = export_resume(
            dossier,
            contact,
            output_path,
            fmt=args.format,
            narrative=narrative,
            cutoff_years=args.cutoff_years,
            today=today,
        )
        notes, pdf_pages = result.notes, result.pdf_pages
    else:
        export_bundle(
            dossier, output_path, fmt=args.format, match_result=match_result, narrative=narrative
        )
    report_lines = narrative_check.report_lines() if narrative_check else []
    if args.json:
        print(
            json.dumps(
                {
                    "output_path": str(output_path),
                    "style": args.style,
                    "narrative": narrative_check.to_dict() if narrative_check else None,
                    "notes": list(notes),
                    "pdf_pages": pdf_pages,
                },
                indent=2,
            )
        )
        return 0
    print(f"[QV] Exported bundle: {output_path}")
    if pdf_pages is not None:
        print(f"[QV] PDF pages: {pdf_pages}")
    for line in report_lines:
        print(f"[QV] {line}")
    for note in notes:
        print(f"[QV] Note: {note}")
    return 0


def _cmd_template_validate(args: argparse.Namespace) -> int:
    """Handle ``qv template validate``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code: ``0`` if valid (or fixed), ``1`` if invalid and
        ``--fix`` was not requested.
    """
    result = templates.validate_template_file(Path(args.path), fix=args.fix)
    if args.json:
        print(json.dumps(result.to_dict()))
    else:
        status = "VALID" if result.valid else "INVALID"
        print(
            f"[QV] Template '{result.template_id}': {status} (weight sum {result.weight_sum:.4f})"
        )
        for issue in result.issues:
            print(f"  - {issue}")
    return 0 if result.valid else 1


def _cmd_vault_set_key(args: argparse.Namespace) -> int:
    """Handle ``qv vault set-key``.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code.

    Raises:
        LLMError: If ``--provider`` isn't a known provider id, or
            ``--timeout`` isn't positive.
        VaultError: If a new vault's passphrase is empty or its
            confirmation doesn't match. Nothing is saved.
    """
    spec = PROVIDERS.get(args.provider)
    if spec is None:
        known = ", ".join(sorted(PROVIDERS))
        raise LLMError(f"Unknown LLM provider '{args.provider}' (known providers: {known})")
    if args.timeout is not None and args.timeout <= 0:
        raise LLMError(f"--timeout must be a positive number of seconds, got {args.timeout:g}")

    workspace_dir = _resolve_workspace_dir(args.dir)
    vault_path = workspace_dir / _VAULT_FILENAME
    passphrase = getpass.getpass("Vault passphrase: ")
    if not vault_path.exists():
        # A new vault: a typo here would lock the user out, so ask twice.
        if not passphrase:
            raise VaultError("A new vault needs a non-empty passphrase; nothing was saved")
        if getpass.getpass("Confirm vault passphrase: ") != passphrase:
            raise VaultError("Passphrases don't match; nothing was saved")

    api_key = ""
    if spec.requires_api_key:
        if spec.api_key_setup_url:
            print(f"[QV] Get a {spec.display_name} API key here: {spec.api_key_setup_url}")
        if spec.setup_note:
            print(f"[QV] Note: {spec.setup_note}")
        api_key = getpass.getpass(f"{spec.display_name} API key: ")
    elif spec.setup_note:
        print(f"[QV] {spec.display_name}: {spec.setup_note}")

    model = args.model or spec.default_model
    host = args.host

    def _set_key(data: VaultData) -> None:
        data.llm_provider = args.provider
        data.llm_model = model
        data.llm_host = host
        data.llm_timeout = args.timeout
        if api_key:
            data.llm_api_keys[args.provider] = api_key

    update_vault(vault_path, passphrase, _set_key)
    print(
        f"[QV] LLM provider '{args.provider}' (model: {model}) "
        f"stored in encrypted vault: {vault_path}"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``qv`` argument parser.

    Returns:
        A configured :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(prog="qv", description="QuestVector career navigation CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    launch = subparsers.add_parser("launch", help="Initialize a local career dossier workspace")
    launch.add_argument("--dir", help="Workspace directory (default: current directory)")
    launch.add_argument("--json", action="store_true", help="Emit JSON output")
    launch.set_defaults(func=_cmd_launch)

    sync_ast = subparsers.add_parser("sync-ast", help="Score a job description against the dossier")
    sync_ast.add_argument("--target", required=True, help="Path to the job description text file")
    sync_ast.add_argument("--template", required=True, help="Mission template id to score against")
    sync_ast.add_argument("--dir", help="Workspace directory (default: current directory)")
    sync_ast.add_argument("--json", action="store_true", help="Emit JSON output")
    sync_ast.set_defaults(func=_cmd_sync_ast)

    export = subparsers.add_parser("export", help="Compile the dossier into a PDF or DOCX bundle")
    export.add_argument("--bundle", required=True, help="Output bundle name (without extension)")
    export.add_argument("--format", required=True, choices=("pdf", "docx"), help="Export format")
    export.add_argument("--dir", help="Workspace directory (default: current directory)")
    export.add_argument(
        "--target", help="Optional job description file to include a match summary for"
    )
    export.add_argument("--template", help="Mission template id (required if --target is given)")
    export.add_argument(
        "--style",
        choices=("report", "resume"),
        default="report",
        help="report: match report plus the whole dossier (default); resume: a one-column "
        "resume that screening software can read (needs Contact.md and role headings "
        f"like '{ROLE_HEADING_EXAMPLE}')",
    )
    export.add_argument(
        "--cutoff-years",
        nargs="?",
        const=DEFAULT_CUTOFF_YEARS,
        default=None,
        type=_cutoff_years_arg,
        metavar="N",
        help=f"With --style resume: move roles that ended more than N years ago "
        f"(default {DEFAULT_CUTOFF_YEARS} when given without a value) to a dateless "
        "Earlier Career line. Off unless given.",
    )
    export.add_argument("--json", action="store_true", help="Emit JSON output")
    export.add_argument(
        "--narrative",
        action="store_true",
        help="Generate an LLM narrative summary (requires vault + --target/--template)",
    )
    export.set_defaults(func=_cmd_export)

    template = subparsers.add_parser("template", help="Mission template operations")
    template_subparsers = template.add_subparsers(dest="template_command", required=True)
    validate = template_subparsers.add_parser("validate", help="Lint a mission template YAML file")
    validate.add_argument("path", help="Path to the mission template YAML file")
    validate.add_argument("--fix", action="store_true", help="Auto-rescale weights to sum to 1.00")
    validate.add_argument("--json", action="store_true", help="Emit JSON output")
    validate.set_defaults(func=_cmd_template_validate)

    vault = subparsers.add_parser("vault", help="Encrypted local vault operations")
    vault_subparsers = vault.add_subparsers(dest="vault_command", required=True)
    set_key = vault_subparsers.add_parser(
        "set-key",
        help="Store an LLM provider (and, for cloud providers, an API key) in the encrypted vault",
    )
    set_key.add_argument(
        "--provider",
        required=True,
        choices=sorted(PROVIDERS),
        help=(
            "LLM provider to configure "
            "(anthropic, openai, gemini -- all remote; ollama -- local, no API key)"
        ),
    )
    set_key.add_argument("--model", help="Model override (default: the provider's default model)")
    set_key.add_argument("--host", help="Server override, used only by --provider ollama")
    set_key.add_argument(
        "--timeout",
        type=float,
        help="Seconds to wait for a response, used only by --provider ollama (default: 300)",
    )
    set_key.add_argument("--dir", help="Workspace directory (default: current directory)")
    set_key.set_defaults(func=_cmd_vault_set_key)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (excluding the program name); defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        The process exit code: ``0`` on success, ``1`` on a handled
        :class:`QuestVectorError`, ``2`` on an unexpected error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.func
    try:
        return handler(args)
    except QuestVectorError as exc:
        print(f"[QV] ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[QV] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
