"""
Tests for unified, side-by-side, and auto-width terminal diff rendering.
"""

from __future__ import annotations

import re

import pytest
from rich.console import Console

from heurix.ui.differ import resolve_diff_style, show_diff


def test_differ_side_by_side_table_and_markup_safety(monkeypatch):
    capture_console = Console(record=True, width=140)
    monkeypatch.setattr("heurix.ui.differ.console", capture_console)

    # 1. Backward-compatible 3-positional-arg unified invocation
    show_diff(
        ".github/workflows/ci.yml",
        "name: CI\non: [push]\n",
        "name: CI\non: [push, pull_request]\n",
    )
    unified_out = capture_console.export_text()
    assert "--- a/.github/workflows/ci.yml (current)" in unified_out
    assert "+++ b/.github/workflows/ci.yml (synthesized)" in unified_out
    assert "[push]" in unified_out
    assert "[push, pull_request]" in unified_out

    # 2. Identical content in side-by-side mode
    identical = "name: CI\non: [push]\n"
    show_diff(".github/workflows/ci.yml", identical, identical, style="side-by-side")
    identical_out = capture_console.export_text()
    assert "No differences in .github/workflows/ci.yml" in identical_out

    # 3. Multi-hunk side-by-side diff with markup hazards, replace/delete/insert, and '...' separator
    old_lines = [
        "name: CI",
        "on: [push]",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - name: Setup",
        "        run: echo setup",
        "      - name: Step A",
        "        run: echo a",
        "      - name: Step B",
        "        run: echo b",
        "      - name: Removed Step",
        "        run: echo old",
        "      - name: Tag check",
        "        run: echo '[bold red]literal[/bold red]'",
    ]
    new_lines = [
        "name: CI",
        "on: [push, pull_request]",
        "jobs:",
        "  test:",
        "    runs-on: ${{ matrix.os }}",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - name: Setup",
        "        run: echo setup",
        "      - name: Step A",
        "        run: echo a",
        "      - name: Step B",
        "        run: echo b",
        "      - name: Tag check",
        "        run: echo '[bold red]literal[/bold red]'",
        "      - name: Added Step",
        "        run: pytest",
    ]
    show_diff(
        ".github/workflows/ci.yml",
        "\n".join(old_lines) + "\n",
        "\n".join(new_lines) + "\n",
        style="side-by-side",
    )
    sbs_out = capture_console.export_text()
    assert "Diff Preview: .github/workflows/ci.yml (side-by-side)" in sbs_out
    assert "(+2 -2 ~2)" in sbs_out
    assert "Current" in sbs_out
    assert "Synthesized" in sbs_out
    assert "│" in sbs_out
    assert "..." in sbs_out
    # Left and right line numbers render accurately alongside content
    assert re.search(r"\b2\s+~\s+on: \[push\]", sbs_out)
    assert re.search(r"\b2\s+~\s+on: \[push, pull_request\]", sbs_out)
    assert re.search(r"\b14\s+-\s+- name: Removed Step", sbs_out)
    assert re.search(r"\b16\s+\+\s+- name: Added Step", sbs_out)
    # Literal Rich-like markup strings and GitHub expressions must survive unparsed
    assert "[push, pull_request]" in sbs_out
    assert "${{ matrix.os }}" in sbs_out
    assert "[bold red]literal[/bold red]" in sbs_out

    # 4. Brand-new file insertion (empty old_content)
    show_diff(
        "k8s/deployment.yaml",
        "",
        "apiVersion: apps/v1\nkind: Deployment\n",
        style="side-by-side",
    )
    new_file_out = capture_console.export_text()
    assert "Diff Preview: k8s/deployment.yaml (side-by-side)" in new_file_out
    assert "(+2 -0 ~0)" in new_file_out
    assert re.search(r"\b1\s+\+\s+apiVersion: apps/v1", new_file_out)

    # 5. Unequal replace spans (both longer new block and longer old block)
    show_diff(
        "replace_check.yml",
        "k1: old1\nk2: mid\nk3: old3\n",
        "k1: new1\nk1b: extra\nk2: mid\n",
        style="side-by-side",
    )
    replace_out = capture_console.export_text()
    assert "(+1 -1 ~1)" in replace_out
    assert "~ k1: new1" in replace_out
    assert "+ k1b: extra" in replace_out
    assert "- k3: old3" in replace_out

    show_diff(
        "replace_shrink.yml",
        "k1: old1\nk1b: extra_old\nk2: mid\n",
        "k1: new1\nk2: mid\n",
        style="side-by-side",
    )
    shrink_out = capture_console.export_text()
    assert "Diff Preview: replace_shrink.yml (side-by-side)" in shrink_out
    assert "(+0 -1 ~1)" in shrink_out
    assert re.search(r"\b1\s+~\s+k1: old1", shrink_out)
    assert re.search(r"\b2\s+-\s+k1b: extra_old", shrink_out)
    assert re.search(r"\b3\s+k2: mid\s+│\s+2\s+k2: mid", shrink_out)


def test_differ_auto_width_and_invalid_style(monkeypatch):
    monkeypatch.delenv("COLUMNS", raising=False)
    capture_console = Console(record=True)
    assert capture_console._width is None
    monkeypatch.setattr("heurix.ui.differ.console", capture_console)

    # Wide terminal via COLUMNS env var -> side-by-side
    monkeypatch.setenv("COLUMNS", "140")
    assert resolve_diff_style("auto") == "side-by-side"
    assert resolve_diff_style(" AUTO ") == "side-by-side"
    show_diff(".github/workflows/ci.yml", "name: Old\n", "name: New\n", style="auto")
    wide_out = capture_console.export_text()
    assert "(side-by-side)" in wide_out
    assert "Current" in wide_out
    assert "Synthesized" in wide_out

    # Narrow terminal via COLUMNS env var -> unified
    monkeypatch.setenv("COLUMNS", "80")
    assert resolve_diff_style("auto") == "unified"
    show_diff(".github/workflows/ci.yml", "name: Old\n", "name: New\n", style="auto")
    narrow_out = capture_console.export_text()
    assert "--- a/.github/workflows/ci.yml (current)" in narrow_out
    assert "+++ b/.github/workflows/ci.yml (synthesized)" in narrow_out

    # Exact 120-column threshold check
    monkeypatch.setenv("COLUMNS", "119")
    assert resolve_diff_style("auto") == "unified"
    monkeypatch.setenv("COLUMNS", "120")
    assert resolve_diff_style("auto") == "side-by-side"

    # Explicit Console width override takes precedence over COLUMNS env var
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr("heurix.ui.differ.console", Console(record=True, width=140))
    assert resolve_diff_style("auto") == "side-by-side"

    monkeypatch.setenv("COLUMNS", "140")
    monkeypatch.setattr("heurix.ui.differ.console", Console(record=True, width=100))
    assert resolve_diff_style("auto") == "unified"

    # Explicit style normalization
    assert resolve_diff_style(" UNIFIED ") == "unified"
    assert resolve_diff_style("Side-By-Side") == "side-by-side"

    # Invalid styles must raise ValueError
    with pytest.raises(ValueError, match="Unsupported diff style"):
        resolve_diff_style("invalid-style")

    with pytest.raises(ValueError, match="Unsupported diff style"):
        show_diff(".github/workflows/ci.yml", "a: 1\n", "a: 2\n", style="split")
