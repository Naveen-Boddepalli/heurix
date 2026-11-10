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


def test_cli_heurix_toml_overrides(tmp_path: Path):
    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / ".heurix.toml").write_text(
        """
[engine]
runner = "ubuntu-22.04"

[ci]
include_dependabot = false
include_k8s = false

[overrides]
python = "3.11"
""",
        encoding="utf-8",
    )

    gen_result = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_result.exit_code == 0

    ci_file = tmp_path / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists()
    content = ci_file.read_text(encoding="utf-8")

    # Runner override applied
    assert "runs-on: ubuntu-22.04" in content
    # Python override applied
    assert "python-version: '3.11'" in content or 'python-version: "3.11"' in content or "python-version: 3.11" in content
    # Dependabot skipped via include_dependabot = false
    assert not (tmp_path / ".github" / "dependabot.yml").exists()
    # K8s skipped via include_k8s = false
    assert not (tmp_path / "k8s").exists()


def test_cli_diff_prompt_loop(tmp_path: Path, monkeypatch):
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    existing_ci = ci_dir / "ci.yml"
    existing_ci.write_text("name: Old CI\njobs: {}\n", encoding="utf-8")

    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    # Simulate user choosing 'diff' first, then 'skip'
    responses = ["diff", "skip"]
    diff_called = []

    def mock_prompt(rel_path, non_interactive=False):
        return responses.pop(0)

    def mock_show_diff(rel_path, old_content, new_content):
        diff_called.append(rel_path)

    monkeypatch.setattr("heurix.cli.prompt_conflict_resolution", mock_prompt)
    monkeypatch.setattr("heurix.cli.show_diff", mock_show_diff)

    result = runner.invoke(app, ["generate", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert len(diff_called) == 1
    # Because user answered 'skip' on re-prompt, existing content is untouched
    assert existing_ci.read_text(encoding="utf-8") == "name: Old CI\njobs: {}\n"


def test_cli_cpp_cmake_generate_and_zero_drift(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\nproject(demo)\nset(CMAKE_CXX_STANDARD 17)\n",
        encoding="utf-8",
    )
    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 0

    check_res = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert check_res.exit_code == 0
    assert "Zero Drift" in check_res.stdout


def test_cli_non_destructive_policy_disabled(tmp_path: Path):
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    existing_ci = ci_dir / "ci.yml"
    existing_ci.write_text(
        """name: Old CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      # @heurix:preserve
      - name: Old Custom Step
        run: echo old
""",
        encoding="utf-8",
    )

    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / ".heurix.toml").write_text(
        """
[engine]
non_destructive = false
""",
        encoding="utf-8",
    )

    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 0

    # With non_destructive = false, SmartMerger is bypassed and old preserved step is overwritten
    content = existing_ci.read_text(encoding="utf-8")
    assert "Old Custom Step" not in content


def test_path_traversal_resolve_safe_path(tmp_path: Path):
    import pytest
    from heurix.cli import resolve_safe_path

    repo = tmp_path / "repo"
    repo.mkdir()

    # Valid repository paths resolve cleanly inside repo
    ci_dest = resolve_safe_path(repo, ".github/workflows/ci.yml")
    assert ci_dest == repo.resolve() / ".github" / "workflows" / "ci.yml"
    k8s_dest = resolve_safe_path(repo, "k8s/deployment.yaml")
    assert k8s_dest == repo.resolve() / "k8s" / "deployment.yaml"

    # Traversal and absolute escape inputs must raise ValueError
    for bad_path in ("../../evil.yml", "../outside.yaml", "a/b/../../../evil.yml", "/etc/passwd"):
        with pytest.raises(ValueError, match="Path traversal security violation"):
            resolve_safe_path(repo, bad_path)

    # Symlink pointing outside repository root must also be rejected
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    escape_link = repo / "escape_link"
    escape_link.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        resolve_safe_path(repo, "escape_link/evil.yml")


def test_path_traversal_blocked_in_generate_and_diff(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".python-version").write_text("3.12", encoding="utf-8")
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    outside_target = tmp_path / "outside_evil.yml"

    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            "../outside_evil.yml": "evil: true\n",
        },
    )

    gen_res = runner.invoke(app, ["generate", "--path", str(repo), "--yes"])
    assert gen_res.exit_code == 1
    normalized_gen = " ".join(gen_res.stdout.split())
    assert "Path traversal security violation" in normalized_gen
    assert not outside_target.exists()

    diff_res = runner.invoke(app, ["diff", "--path", str(repo)])
    assert diff_res.exit_code == 1
    normalized_diff = " ".join(diff_res.stdout.split())
    assert "Path traversal security violation" in normalized_diff
    assert not outside_target.exists()

    # Also test absolute destination injection
    abs_target = tmp_path / "abs_evil.yml"
    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            str(abs_target): "evil: true\n",
        },
    )
    abs_res = runner.invoke(app, ["generate", "--path", str(repo), "--yes"])
    assert abs_res.exit_code == 1
    assert not abs_target.exists()


def test_cli_yaml_syntax_error_exits_cleanly(tmp_path: Path):
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    malformed_content = "name: Broken CI\njobs:\n  test: [unclosed\n"
    ci_file = ci_dir / "ci.yml"
    ci_file.write_text(malformed_content, encoding="utf-8")

    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 1
    assert isinstance(gen_res.exception, SystemExit)
    normalized_out = " ".join(gen_res.stdout.split())
    assert "YAML Syntax Error" in normalized_out
    assert ".github/workflows/ci.yml" in normalized_out
    assert "Traceback" not in gen_res.stdout
    # Existing malformed file must NOT be silently overwritten
    assert ci_file.read_text(encoding="utf-8") == malformed_content

    diff_res = runner.invoke(app, ["diff", "--path", str(tmp_path)])
    assert diff_res.exit_code == 1
    assert isinstance(diff_res.exception, SystemExit)
    assert "YAML Syntax Error" in " ".join(diff_res.stdout.split())
    assert "Traceback" not in diff_res.stdout

