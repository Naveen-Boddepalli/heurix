"""
Colorized Visual Diff and Terminal Diff Viewer.
"""

from __future__ import annotations

import difflib
import shutil

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

_SUPPORTED_DIFF_STYLES = frozenset({"unified", "side-by-side", "auto"})
_SIDE_BY_SIDE_MIN_WIDTH = 120


def resolve_diff_style(style: str = "unified") -> str:
    """
    Validate and resolve a diff rendering style ('unified', 'side-by-side', or 'auto').

    When 'auto' is requested, returns 'side-by-side' if the active console has an
    explicit width >= 120 or the terminal width is >= 120 columns; otherwise 'unified'.
    """
    normalized = (style or "unified").strip().lower()
    if normalized not in _SUPPORTED_DIFF_STYLES:
        raise ValueError(
            f"Unsupported diff style '{style}'. Expected 'unified', 'side-by-side', or 'auto'."
        )

    if normalized == "auto":
        explicit_width = getattr(console, "_width", None)
        cols = (
            explicit_width
            if explicit_width is not None
            else shutil.get_terminal_size(fallback=(80, 24)).columns
        )
        return "side-by-side" if cols >= _SIDE_BY_SIDE_MIN_WIDTH else "unified"

    return normalized


def _render_unified_diff(file_path: str, old_content: str, new_content: str) -> None:
    """Render a unified colorized terminal diff inside a Rich Panel."""
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
        console.print(f"[dim]No differences in {escape(file_path)}[/dim]")
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
            title=f"[bold]Diff Preview: {escape(file_path)}[/bold]",
            border_style="cyan",
        )
    )


def _render_side_by_side(file_path: str, old_content: str, new_content: str) -> None:
    """Render a two-column Rich Table diff preview with line numbers and markup safety."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    groups = list(difflib.SequenceMatcher(None, old_lines, new_lines).get_grouped_opcodes(n=3))

    if not groups:
        console.print(f"[dim]No differences in {escape(file_path)}[/dim]")
        return

    table = Table(
        expand=True,
        show_header=True,
        header_style="bold cyan",
        box=box.SIMPLE,
        pad_edge=False,
    )
    table.add_column("#", justify="right", style="dim", min_width=4, no_wrap=True)
    table.add_column("Current", ratio=1, overflow="fold")
    table.add_column("│", width=1, style="dim", no_wrap=True)
    table.add_column("#", justify="right", style="dim", min_width=4, no_wrap=True)
    table.add_column("Synthesized", ratio=1, overflow="fold")

    def _add_row(
        left_num: str,
        left_text: str,
        left_style: str,
        right_num: str,
        right_text: str,
        right_style: str,
    ) -> None:
        table.add_row(
            left_num,
            Text(left_text, style=left_style),
            "│",
            right_num,
            Text(right_text, style=right_style),
        )

    added = 0
    removed = 0
    modified = 0

    for group_idx, group in enumerate(groups):
        if group_idx > 0:
            _add_row("...", "...", "dim", "...", "...", "dim")

        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for oi, ni in zip(range(i1, i2), range(j1, j2)):
                    _add_row(
                        str(oi + 1),
                        f"  {old_lines[oi]}",
                        "dim",
                        str(ni + 1),
                        f"  {new_lines[ni]}",
                        "dim",
                    )
            elif tag == "delete":
                for oi in range(i1, i2):
                    removed += 1
                    _add_row(str(oi + 1), f"- {old_lines[oi]}", "red", "", "", "dim")
            elif tag == "insert":
                for ni in range(j1, j2):
                    added += 1
                    _add_row("", "", "dim", str(ni + 1), f"+ {new_lines[ni]}", "green")
            elif tag == "replace":
                len_old = i2 - i1
                len_new = j2 - j1
                for offset in range(max(len_old, len_new)):
                    has_old = offset < len_old
                    has_new = offset < len_new
                    if has_old and has_new:
                        modified += 1
                        _add_row(
                            str(i1 + offset + 1),
                            f"~ {old_lines[i1 + offset]}",
                            "yellow",
                            str(j1 + offset + 1),
                            f"~ {new_lines[j1 + offset]}",
                            "yellow",
                        )
                    elif has_old:
                        removed += 1
                        _add_row(
                            str(i1 + offset + 1),
                            f"- {old_lines[i1 + offset]}",
                            "red",
                            "",
                            "",
                            "dim",
                        )
                    else:
                        added += 1
                        _add_row(
                            "",
                            "",
                            "dim",
                            str(j1 + offset + 1),
                            f"+ {new_lines[j1 + offset]}",
                            "green",
                        )

    console.print(
        Panel(
            table,
            title=(
                f"[bold]Diff Preview: {escape(file_path)} (side-by-side)[/bold] "
                f"[dim](+{added} -{removed} ~{modified})[/dim]"
            ),
            border_style="cyan",
        )
    )


def show_diff(
    file_path: str,
    old_content: str,
    new_content: str,
    style: str = "unified",
) -> None:
    """
    Render a colorized terminal diff between existing and synthesized content.

    Supports 'unified', 'side-by-side', and 'auto' (>=120 columns -> side-by-side).
    """
    resolved_style = resolve_diff_style(style)
    if resolved_style == "side-by-side":
        _render_side_by_side(file_path, old_content, new_content)
    else:
        _render_unified_diff(file_path, old_content, new_content)
