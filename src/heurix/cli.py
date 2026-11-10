"""
Heurix CLI (hx): Deterministic Codebase Scanner & YAML Synthesizer.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel

from heurix import __version__
from heurix.core.drift import DriftDetector
from heurix.core.merger import SmartMerger, YamlSyntaxError
from heurix.core.validator import PreflightValidator
from heurix.detectors import analyze_repository
from heurix.synthesizers import synthesize_all
from heurix.ui.console import print_banner, print_explain_tree, print_summary_table
from heurix.ui.differ import show_diff
from heurix.ui.prompts import prompt_conflict_resolution

app = typer.Typer(
    name="hx",
    help="Deterministic Codebase Scanner & Automated YAML Synthesizer.",
    no_args_is_help=False,
    add_completion=False,
)
console = Console()


def resolve_safe_path(base_dir: Path, rel_path: str | Path) -> Path:
    """
    Resolve rel_path against base_dir and verify strict containment within base_dir.
    Raises ValueError on any path traversal or symlink escape attempt.
    """
    base_resolved = base_dir.resolve()
    target_resolved = (base_resolved / rel_path).resolve()
    if not target_resolved.is_relative_to(base_resolved):
        raise ValueError(
            f"Path traversal security violation: path '{rel_path}' resolves outside repository root '{base_dir}'"
        )
    return target_resolved


def _resolve_or_exit(repo_path: Path, rel_path: str | Path) -> Path:
    """Resolve a repository-relative target path or display an error panel and exit(1)."""
    try:
        return resolve_safe_path(repo_path, rel_path)
    except ValueError as e:
        console.print(
            Panel.fit(
                f"[bold red]Security Error:[/bold red] {e}",
                title="Path Traversal Blocked",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)


def version_callback(value: bool):
    if value:
        console.print(f"[bold cyan]Heurix (hx)[/bold cyan] version [green]{__version__}[/green]")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True, help="Show version."
    ),
):
    """
    Heurix CLI (alias: hx). Run 'hx generate' to scan and synthesize YAML configs.
    """
    if ctx.invoked_subcommand is None:
        # Default behavior when running 'hx' without subcommand
        generate(
            path=".",
            explain=True,
            dry_run=False,
            diff=False,
            yes=False,
            k8s=True,
        )


@app.command()
def generate(
    path: str = typer.Option(".", "--path", "-p", help="Root directory of the repository to scan."),
    explain: bool = typer.Option(True, "--explain/--no-explain", help="Show step-by-step heuristic reasoning log."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview synthesized files without writing to disk."),
    diff: bool = typer.Option(False, "--diff", "-d", help="Show terminal diff of proposed changes."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive mode (auto-apply without prompts)."),
    k8s: bool = typer.Option(True, "--k8s/--no-k8s", help="Synthesize Kubernetes manifests if containerized."),
):
    """
    Scan codebase and synthesize deterministic CI/CD and infrastructure YAML files.
    """
    print_banner()

    repo_path = Path(path).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        console.print(f"[bold red]Error:[/bold red] Directory '{path}' does not exist.")
        raise typer.Exit(code=1)

    # 1. Scan and analyze repository into ProjectContext IR
    with console.status("[bold cyan]Scanning repository and running heuristic detectors...[/bold cyan]"):
        context = analyze_repository(repo_path)

    # 2. Render explain reasoning tree if requested
    if explain:
        print_explain_tree(context)

    # 3. Synthesize YAML outputs
    ci_cfg = context.policy_config.get("ci", {})
    include_dependabot = ci_cfg.get("include_dependabot", True)
    include_k8s = ci_cfg.get("include_k8s", k8s) if k8s else False

    synthesized = synthesize_all(context, include_k8s=include_k8s, include_dependabot=include_dependabot)
    if not synthesized:
        console.print("[yellow]No relevant languages or container configs detected to synthesize.[/yellow]")
        return

    # Validate repository boundary containment for all candidate output paths before validation or I/O
    for rel_path in synthesized:
        _resolve_or_exit(repo_path, rel_path)

    # 4. Pre-Flight Validation
    validator = PreflightValidator()
    all_valid = True
    for rel_path, content in synthesized.items():
        is_valid, errors = validator.validate(rel_path, content)
        if not is_valid:
            all_valid = False
            console.print(f"[bold red]Validation failed for '{rel_path}':[/bold red]")
            for err in errors:
                console.print(f"  [red]✖ {err}[/red]")

    if not all_valid:
        console.print("[bold red]Pre-flight validation failed. Aborting write to protect repository.[/bold red]")
        raise typer.Exit(code=1)

    # 5. Diff preview or smart merge
    merger = SmartMerger()
    files_to_write: dict[str, str] = {}
    engine_cfg = context.policy_config.get("engine", {})
    non_destructive = engine_cfg.get("non_destructive", True)

    for rel_path, new_content in synthesized.items():
        target_file = _resolve_or_exit(repo_path, rel_path)
        if target_file.exists():
            existing_content = target_file.read_text(encoding="utf-8", errors="replace")
            try:
                merged_content = (
                    merger.merge_yaml(existing_content, new_content)
                    if non_destructive
                    else new_content
                )
            except YamlSyntaxError as e:
                console.print(
                    Panel.fit(
                        f"[bold red]YAML Syntax Error in '{rel_path}':[/bold red]\n{e}\n"
                        "[dim]Fix the malformed YAML file or set non_destructive = false in .heurix.toml.[/dim]",
                        title="Merge Aborted",
                        border_style="red",
                    )
                )
                raise typer.Exit(code=1)

            if diff:
                show_diff(rel_path, existing_content, merged_content)

            if not dry_run and not yes:
                while True:
                    choice = prompt_conflict_resolution(rel_path, non_interactive=yes)
                    if choice == "diff":
                        show_diff(rel_path, existing_content, merged_content)
                        continue
                    break

                if choice == "skip":
                    console.print(f"[dim]Skipped {rel_path}[/dim]")
                    continue
                elif choice == "backup":
                    backup_path = _resolve_or_exit(repo_path, f"{rel_path}.bak")
                    shutil.copyfile(target_file, backup_path)
                    console.print(f"[green]Backup created at {backup_path.name}[/green]")

            files_to_write[rel_path] = merged_content
        else:
            if diff:
                show_diff(rel_path, "", new_content)
            files_to_write[rel_path] = new_content

    # 6. Summary Table
    print_summary_table(files_to_write, dry_run=dry_run)

    # 7. Write to disk if not dry_run
    if dry_run:
        console.print("\n[yellow]Dry run completed. No files were written to disk.[/yellow]")
        return

    for rel_path, content in files_to_write.items():
        dest = _resolve_or_exit(repo_path, rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        console.print(f"[bold green]✔ Written:[/bold green] [cyan]{rel_path}[/cyan]")

    console.print(
        Panel.fit(
            f"[bold green]Successfully synthesized {len(files_to_write)} file(s)![/bold green]\n"
            "[dim]Deterministic, schema-validated, and non-destructively merged.[/dim]",
            border_style="green",
        )
    )


@app.command()
def diff(
    path: str = typer.Option(".", "--path", "-p", help="Root directory of repository."),
    k8s: bool = typer.Option(True, "--k8s/--no-k8s", help="Include Kubernetes manifests."),
):
    """
    Compare current repository state with synthesized configs without writing changes.
    """
    generate(path=path, explain=False, dry_run=True, diff=True, yes=True, k8s=k8s)


@app.command()
def check(
    path: str = typer.Option(".", "--path", "-p", help="Root directory of repository."),
):
    """
    Continuous drift detection: verifies whether existing YAML configs match codebase requirements.
    Exits with code 1 if drift is detected (ideal for CI and git pre-commit hooks).
    """
    repo_path = Path(path).resolve()
    context = analyze_repository(repo_path)
    ci_cfg = context.policy_config.get("ci", {})
    include_dependabot = ci_cfg.get("include_dependabot", True)
    include_k8s = ci_cfg.get("include_k8s", False)
    synthesized = synthesize_all(context, include_k8s=include_k8s, include_dependabot=include_dependabot)

    detector = DriftDetector(repo_path)
    findings = detector.check_drift(context, synthesized)

    if not findings:
        console.print("[bold green]✔ Zero Drift Detected:[/bold green] CI/CD workflows are completely synchronized with the codebase!")
        raise typer.Exit(code=0)

    console.print(f"[bold yellow]⚠️ Drift Detected ({len(findings)} issue(s)):[/bold yellow]\n")
    for f in findings:
        color = "red" if f.severity == "ERROR" else "yellow"
        console.print(f"[{color}][bold]{f.file_path}:[/bold] {f.issue}[/{color}]")
        console.print(f"  [dim]↳ Recommendation: {f.recommendation}[/dim]\n")

    raise typer.Exit(code=1)


@app.command()
def scan(
    path: str = typer.Option(".", "--path", "-p", help="Root directory of repository."),
):
    """
    Scan codebase and output the strongly-typed ProjectContext Intermediate Representation (IR).
    """
    repo_path = Path(path).resolve()
    context = analyze_repository(repo_path)
    console.print_json(context.model_dump_json(indent=2))


@app.command()
def init(
    path: str = typer.Option(".", "--path", "-p", help="Root directory of repository."),
):
    """
    Initialize a minimal .heurix.toml policy configuration for power users.
    """
    repo_path = Path(path).resolve()
    config_file = _resolve_or_exit(repo_path, ".heurix.toml")
    if config_file.exists():
        console.print("[yellow].heurix.toml already exists.[/yellow]")
        return

    content = """# Heurix Configuration Policy (.heurix.toml)
# Optional configuration overrides for power users.

[engine]
runner = "ubuntu-latest"
non_destructive = true

[ci]
include_dependabot = true
include_k8s = true

[overrides]
# Force specific runtime versions if desired:
# python = "3.12"
# node = "20.x"
"""
    config_file.write_text(content, encoding="utf-8")
    console.print("[bold green]✔ Initialized .heurix.toml policy file.[/bold green]")


if __name__ == "__main__":
    app()
