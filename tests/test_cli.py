"""
Tests for Heurix CLI Commands.
"""

from __future__ import annotations

from pathlib import Path
from typer.testing import CliRunner
from heurix.cli import app

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_cli_init(tmp_path: Path):
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".heurix.toml").exists()


def test_cli_scan_json(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
    result = runner.invoke(app, ["scan", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert '"repo_name"' in result.stdout
    assert '"python"' in result.stdout


def test_cli_generate_dry_run(tmp_path: Path):
    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    result = runner.invoke(app, ["generate", "--path", str(tmp_path), "--dry-run", "--yes"])
    assert result.exit_code == 0
    assert "Dry run completed" in result.stdout
    assert not (tmp_path / ".github" / "workflows" / "ci.yml").exists()


def test_cli_generate_and_drift(tmp_path: Path):
    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    # Generate actual files
    gen_result = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_result.exit_code == 0
    assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()

    # Check drift -> should be 0 drift
    check_result = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert check_result.exit_code == 0
    assert "Zero Drift" in check_result.stdout
