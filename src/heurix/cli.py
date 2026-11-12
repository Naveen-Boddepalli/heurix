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
from rich.markup import escape
from rich.panel import Panel

from heurix import __version__
from heurix.core.context import ProjectContext
from heurix.core.drift import DriftDetector
from heurix.core.hooks import install_pre_commit_hook
from heurix.core.merger import SmartMerger, YamlSyntaxError
from heurix.core.policy import HeurixPolicy
from heurix.core.validator import PreflightValidator
from heurix.detectors import analyze_repository
from heurix.synthesizers import synthesize_all
from heurix.ui.console import (
    print_banner,
    print_explain_tree,
    print_summary_table,
    print_validation_warnings,
)
from heurix.ui.differ import resolve_diff_style, show_diff
from heurix.ui.prompts import (
    prompt_backing_services,
    prompt_conflict_resolution,
    prompt_deployment_targets,
    prompt_e2e_split,
    prompt_install_hooks,
    prompt_k8s_generation,
    resolve_context_ambiguities,
)

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


def _synthesize_or_exit(
    context: ProjectContext,
    *,
    include_k8s: bool,
    include_dependabot: bool,
) -> dict[str, str]:
    """Run synthesize_all() and exit cleanly with code 1 on SEC-01 template/path ValueError."""
    try:
        return synthesize_all(
            context,
            include_k8s=include_k8s,
            include_dependabot=include_dependabot,
        )
    except ValueError as e:
        console.print(
            Panel.fit(
                f"[bold red]Security Error:[/bold red] {e}",
                title="Template / Path Security Error",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)


def version_callback(value: bool):
    if value:
        console.print(f"[bold cyan]Heurix (hx)[/bold cyan] version [green]{__version__}[/green]")
        raise typer.Exit()


def _run_generate(
    *,
    path: str = ".",
    explain: bool = True,
    dry_run: bool = False,
    diff: bool = False,
    yes: bool = False,
    non_interactive: bool = False,
    k8s: bool = True,
    side_by_side: bool = False,
    diff_style: str = "unified",
    strict: bool = False,
) -> None:
    """Core generate/diff workflow using pure Python arguments (safe from Typer OptionInfo)."""
    effective_diff_style = ("side-by-side" if side_by_side else (diff_style or "unified")).strip().lower()
    try:
        resolve_diff_style(effective_diff_style)
    except ValueError as e:
        console.print(
            Panel.fit(
                f"[bold red]Invalid Diff Style:[/bold red] {escape(str(e))}",
                title="Invalid Argument",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

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

    # 3. Resolve policy and interactive ambiguities
    policy = HeurixPolicy.from_raw(context.policy_config)
    include_dependabot = policy.ci.include_dependabot
    include_k8s = (policy.ci.include_k8s if policy.ci.include_k8s is not None else k8s) if k8s else False
    headless = yes or non_interactive

    if not headless:
        context, include_k8s = resolve_context_ambiguities(
            context,
            include_k8s=include_k8s,
            k8s_policy_explicit=(not k8s or policy.ci.include_k8s is not None),
            services_policy_explicit=bool(policy.services.exclude),
            non_interactive=headless,
            e2e_prompt=prompt_e2e_split,
            targets_prompt=prompt_deployment_targets,
            services_prompt=prompt_backing_services,
            k8s_prompt=prompt_k8s_generation,
        )

    # 4. Synthesize YAML outputs
    synthesized = _synthesize_or_exit(
        context,
        include_k8s=include_k8s,
        include_dependabot=include_dependabot,
    )
    if not synthesized:
        console.print("[yellow]No relevant languages or container configs detected to synthesize.[/yellow]")
        return

    # Validate repository boundary containment for all candidate output paths before validation or I/O
    for rel_path in synthesized:
        _resolve_or_exit(repo_path, rel_path)

    # 5. Granular Pre-Flight Validation
    validator = PreflightValidator()
    outcome = validator.validate_batch(synthesized, strict=strict)

    if outcome.has_critical_errors:
        for rel_path, errors in outcome.critical_errors.items():
            console.print(f"[bold red]Validation failed for '{escape(rel_path)}':[/bold red]")
            for err in errors:
                console.print(f"  [red]✖ {escape(err)}[/red]")
        console.print("[bold red]Pre-flight validation failed. Aborting write to protect repository.[/bold red]")
        raise typer.Exit(code=1)

    if outcome.has_warnings:
        print_validation_warnings(outcome.optional_warnings)
        synthesized = dict(outcome.valid_files)
        if not synthesized:
            console.print(
                "[yellow]No valid configurations remain after excluding optional manifests with warnings.[/yellow]"
            )
            return

    def _render_diff(rel_path: str, old_text: str, new_text: str) -> None:
        if effective_diff_style == "unified":
            show_diff(rel_path, old_text, new_text)
        else:
            show_diff(rel_path, old_text, new_text, style=effective_diff_style)

    # 6. Diff preview or smart merge
    merger = SmartMerger()
    files_to_write: dict[str, str] = {}
    non_destructive = policy.engine.non_destructive

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
                _render_diff(rel_path, existing_content, merged_content)

            if not dry_run and not headless:
                while True:
                    choice = prompt_conflict_resolution(rel_path, non_interactive=headless)
                    if choice == "diff":
                        _render_diff(rel_path, existing_content, merged_content)
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
                _render_diff(rel_path, "", new_content)
            files_to_write[rel_path] = new_content

    # 7. Summary Table
    print_summary_table(files_to_write, dry_run=dry_run)

    # 8. Write to disk if not dry_run
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
        _run_generate(
            path=".",
            explain=True,
            dry_run=False,
            diff=False,
            yes=False,
            non_interactive=False,
            k8s=True,
            side_by_side=False,
            diff_style="unified",
            strict=False,
        )


@app.command()
def generate(
    path: str = typer.Option(".", "--path", "-p", help="Root directory of the repository to scan."),
    explain: bool = typer.Option(True, "--explain/--no-explain", help="Show step-by-step heuristic reasoning log."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview synthesized files without writing to disk."),
    diff: bool = typer.Option(False, "--diff", "-d", help="Show terminal diff of proposed changes."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive mode (auto-apply without prompts)."),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Disable interactive prompts and use deterministic defaults."
    ),
    k8s: bool = typer.Option(True, "--k8s/--no-k8s", help="Synthesize Kubernetes manifests if containerized."),
    side_by_side: bool = typer.Option(False, "--side-by-side", help="Render side-by-side diff tables."),
    diff_style: str = typer.Option(
        "unified", "--diff-style", help="Diff style: unified, side-by-side, or auto."
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Treat optional manifest validation warnings as fatal errors."
    ),
):
    """
    Scan codebase and synthesize deterministic CI/CD and infrastructure YAML files.
    """
    _run_generate(
        path=path,
        explain=explain,
        dry_run=dry_run,
        diff=diff,
        yes=yes,
        non_interactive=non_interactive,
        k8s=k8s,
        side_by_side=side_by_side,
        diff_style=diff_style,
        strict=strict,
    )


@app.command()
def diff(
    path: str = typer.Option(".", "--path", "-p", help="Root directory of repository."),
    k8s: bool = typer.Option(True, "--k8s/--no-k8s", help="Include Kubernetes manifests."),
    side_by_side: bool = typer.Option(False, "--side-by-side", help="Render side-by-side diff tables."),
    diff_style: str = typer.Option(
        "unified", "--diff-style", help="Diff style: unified, side-by-side, or auto."
    ),
):
    """
    Compare current repository state with synthesized configs without writing changes.
    """
    _run_generate(
        path=path,
        explain=False,
        dry_run=True,
        diff=True,
        yes=True,
        non_interactive=True,
        k8s=k8s,
        side_by_side=side_by_side,
        diff_style=diff_style,
        strict=False,
    )


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
    policy = HeurixPolicy.from_raw(context.policy_config)
    include_dependabot = policy.ci.include_dependabot
    include_k8s = bool(policy.ci.include_k8s)
    synthesized = _synthesize_or_exit(
        context,
        include_k8s=include_k8s,
        include_dependabot=include_dependabot,
    )

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
    hooks: Optional[bool] = typer.Option(
        None,
        "--hooks/--no-hooks",
        help="Install an idempotent Git pre-commit hook running 'hx check'.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive mode (accept defaults without prompting).",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Disable interactive prompts.",
    ),
):
    """
    Initialize a minimal .heurix.toml policy configuration for power users.
    """
    repo_path = Path(path).resolve()
    config_file = _resolve_or_exit(repo_path, ".heurix.toml")
    if config_file.exists():
        console.print("[yellow].heurix.toml already exists.[/yellow]")
    else:
        content = """# Heurix Configuration Policy (.heurix.toml)
# Deterministic CI/CD, Dependabot, and Kubernetes policy configuration.

[engine]
runner = "ubuntu-latest"
non_destructive = true
# templates_dir = ".heurix/templates"  # Repo-local Jinja2 override directory (contained inside repo)

[ci]
include_dependabot = true
include_k8s = true
# default_branch = "main"
# pin_actions = true
#
# [ci.action_shas]
# "actions/checkout" = "<40-char-commit-sha>"
#
# [ci.runners]
# test-apps-web = "ubuntu-24.04-arm"
# deploy_vercel = "ubuntu-latest"
#
# [[ci.steps.pre_test]]
# name = "Pre-test check"
# run = "echo Running pre-test hooks"
#
# [[ci.steps.post_test]]
# name = "Post-test cleanup"
# run = "echo Done"

[overrides]
# Force specific runtime versions if desired:
# python = "3.12"
# node = "20.x"

# [matrix]
# os = ["ubuntu-latest", "macos-latest"]
# python = ["3.11", "3.12"]

# [jobs.test]  # Also supports any [jobs.<id>]
# runner = "ubuntu-latest"
# [[jobs.test.pre_steps]]
# name = "Job pre-step"
# run = "echo pre"
# [[jobs.test.post_steps]]
# name = "Job post-step"
# run = "echo post"

# [services]
# exclude = ["redis"]

# [env]
# APP_ENV = "ci"

# [secrets]
# test = ["TEST_API_TOKEN"]
# deploy = ["VERCEL_TOKEN"]

# [linters]
# enabled = true
# python = true
# node = true
# go = true
# rust = true
# cpp = true

# [kubernetes]  # Alias: [k8s]
# replicas = 2
# namespace = "production"
# image = "my-app:latest"
# port = 8000
# service_type = "ClusterIP"  # ClusterIP | NodePort | LoadBalancer
#
# [kubernetes.resources.requests]
# cpu = "100m"
# memory = "256Mi"
#
# [kubernetes.resources.limits]
# cpu = "500m"
# memory = "512Mi"
#
# [kubernetes.liveness_probe]
# enabled = true
# type = "httpGet"  # httpGet | tcpSocket | exec
# path = "/health"
# initial_delay_seconds = 15
# period_seconds = 10
#
# [kubernetes.readiness_probe]
# enabled = true
# type = "httpGet"
# path = "/health"
# initial_delay_seconds = 5
# period_seconds = 10
#
# [kubernetes.hpa]
# enabled = true
# min_replicas = 2
# max_replicas = 10
# target_cpu_utilization = 80
"""
        config_file.write_text(content, encoding="utf-8")
        console.print("[bold green]✔ Initialized .heurix.toml policy file.[/bold green]")

    headless = yes or non_interactive
    install_hooks = False
    if hooks is False:
        install_hooks = False
    elif hooks is True:
        install_hooks = True
    else:
        raw_git = repo_path / ".git"
        if raw_git.exists() or raw_git.is_symlink():
            git_entry = _resolve_or_exit(repo_path, ".git")
            if git_entry.is_dir() and not headless:
                install_hooks = bool(prompt_install_hooks(non_interactive=False))

    if install_hooks:
        try:
            hook_result = install_pre_commit_hook(repo_path, resolve_safe_path)
        except ValueError as e:
            console.print(
                Panel.fit(
                    f"[bold red]Security Error:[/bold red] {e}",
                    title="Path Traversal Blocked",
                    border_style="red",
                )
            )
            raise typer.Exit(code=1)

        if hook_result.status == "created":
            console.print(
                f"[bold green]✔ Installed pre-commit hook:[/bold green] [cyan]{escape(str(hook_result.hook_path))}[/cyan]"
            )
        elif hook_result.status == "updated":
            console.print(
                f"[bold green]✔ Updated pre-commit hook:[/bold green] [cyan]{escape(str(hook_result.hook_path))}[/cyan]"
            )
        elif hook_result.status == "unchanged":
            console.print(
                f"[green]✔ Pre-commit hook already up to date:[/green] [cyan]{escape(str(hook_result.hook_path))}[/cyan]"
            )
        elif hook_result.status == "skipped_no_git":
            console.print(f"[yellow]⚠ {escape(hook_result.message)}[/yellow]")
        elif hook_result.status == "error":
            border = "red" if hooks is True else "yellow"
            title = "Pre-Commit Hook Error" if hooks is True else "Pre-Commit Hook Warning"
            console.print(
                Panel.fit(
                    f"[bold {border}]{title}:[/bold {border}] {escape(hook_result.message)}",
                    title=title,
                    border_style=border,
                )
            )
            if hooks is True:
                raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
