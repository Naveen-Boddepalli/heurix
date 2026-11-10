"""
Colorized Visual Diff and Terminal Diff Viewer.
"""

from __future__ import annotations

import difflib
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def show_diff(file_path: str, old_content: str, new_content: str) -> None:
    """
    Renders a unified colorized terminal diff between existing and new content.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path} (current)",
            tofile=f"b/{file_path} (synthesized)",
            n=3,
        )
    )

    if not diff:
        console.print(f"[dim]No differences in {file_path}[/dim]")
        return

    diff_text = Text()
    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            diff_text.append(line, style="bold cyan")
        elif line.startswith("@@"):
            diff_text.append(line, style="bold magenta")
        elif line.startswith("+"):
            diff_text.append(line, style="green")
        elif line.startswith("-"):
            diff_text.append(line, style="red")
        else:
            diff_text.append(line, style="dim white")

    console.print(
        Panel(
            diff_text,
            title=f"[bold]Diff Preview: {file_path}[/bold]",
            border_style="cyan",
        )
    )
