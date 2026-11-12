"""
Rich Terminal Console and Explainability Tree Renderer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from heurix.core.context import ProjectContext

console = Console()


def print_banner() -> None:
    """Print the Heurix CLI header banner."""
    console.print(
        Panel.fit(
            "[bold cyan]Heurix (hx)[/bold cyan] — [dim]Deterministic Codebase Scanner & YAML Synthesizer[/dim]\n"
            "[italic green]100% Deterministic • Offline-Capable • Deep Heuristic Analysis[/italic green]",
            border_style="cyan",
        )
    )


def print_explain_tree(context: ProjectContext) -> None:
    """
    Renders an explainable reasoning tree showing every heuristic triggered.
    """
    tree = Tree(f"[bold cyan]🔍 Codebase Scan: {context.repo_name}[/bold cyan]")

    for step in context.explain_log:
        if "detected" in step.lower() or "inferred" in step.lower() or "parsed" in step.lower():
            tree.add(f"[green]✔[/green] {step}")
        elif "warning" in step.lower():
            tree.add(f"[yellow]⚠[/yellow] {step}")
        else:
            tree.add(f"[dim]{step}[/dim]")

    console.print(tree)
    console.print()


def print_summary_table(synthesized_files: dict[str, str], dry_run: bool = False) -> None:
    """
    Prints a summary table of synthesized YAML configurations.
    """
    table = Table(title="✨ Synthesized Configurations", border_style="cyan")
    table.add_column("File Path", style="bold white")
    table.add_column("Type / Target", style="magenta")
    table.add_column("Lines", justify="right", style="cyan")
    table.add_column("Action", style="green")

    for path, content in synthesized_files.items():
        lines_count = len(content.splitlines())
        target = "GitHub Actions CI"
        if "dependabot" in path:
            target = "Dependabot Maintenance"
        elif "kind" in path:
            target = "Kind Cluster Config"
        elif "k8s" in path:
            target = "Kubernetes Manifest"

        action = "[yellow]Dry Run (Preview)[/yellow]" if dry_run else "[green]Ready to Write[/green]"
        table.add_row(path, target, str(lines_count), action)

    console.print(table)


def print_validation_warnings(warnings_by_file: Mapping[str, Sequence[str]]) -> None:
    """
    Render a yellow Rich warning Panel listing excluded optional manifests and errors.
    """
    if not warnings_by_file:
        return

    body = Text()
    for idx, (rel_path, errors) in enumerate(warnings_by_file.items()):
        if idx > 0:
            body.append("\n")
        body.append(f"• {rel_path}\n", style="bold yellow")
        for err in errors:
            body.append(f"  ⚠ {err}\n", style="yellow")

    body.append(
        "\nExcluded failing optional manifest(s). Re-run with --strict to treat optional warnings as fatal.",
        style="dim",
    )

    console.print(
        Panel(
            body,
            title="[bold yellow]Optional Manifest Warnings (Excluded)[/bold yellow]",
            border_style="yellow",
        )
    )

