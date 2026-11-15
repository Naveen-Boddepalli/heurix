"""
End-to-end regression tests for issues found by running `hx` against sample repositories.
"""

from __future__ import annotations

import json
from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from heurix.cli import app

runner = CliRunner()


def _generate(repo: Path) -> dict:
    res = runner.invoke(app, ["generate", "--path", str(repo), "--yes", "--non-interactive", "--no-k8s"])
    assert res.exit_code == 0, res.stdout
    return YAML(typ="safe").load((repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _steps(doc: dict, job: str = "test") -> list:
    return doc["jobs"][job]["steps"]


def test_psycopg3_dependency_provisions_postgres_service(tmp_path: Path):
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["fastapi", "psycopg[binary]>=3.1", "pytest"]\n',
        encoding="utf-8",
    )
    doc = _generate(tmp_path)
    assert "postgres" in doc["jobs"]["test"].get("services", {})


def test_pnpm_package_manager_field_is_not_duplicated_in_action_setup(tmp_path: Path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "w", "packageManager": "pnpm@9.12.0", "scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )
    doc = _generate(tmp_path)
    pnpm_step = next(s for s in _steps(doc) if "pnpm/action-setup" in s.get("uses", ""))
    assert "version" not in (pnpm_step.get("with") or {})


def test_pnpm_without_package_manager_field_keeps_explicit_version(tmp_path: Path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "w", "scripts": {"test": "vitest run"}}), encoding="utf-8"
    )
    doc = _generate(tmp_path)
    pnpm_step = next(s for s in _steps(doc) if "pnpm/action-setup" in s.get("uses", ""))
    assert pnpm_step["with"]["version"] == "9"


def test_poetry_installed_before_setup_python_poetry_cache(tmp_path: Path):
    (tmp_path / "poetry.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\nversion = "0.1.0"\n'
        '[tool.poetry.dependencies]\npython = "^3.11"\n'
        '[tool.poetry.group.dev.dependencies]\npytest = "^8"\n',
        encoding="utf-8",
    )
    uses = [s.get("uses", "") for s in _steps(_generate(tmp_path))]
    poetry_idx = next(i for i, u in enumerate(uses) if "snok/install-poetry" in u)
    setup_py_idx = next(i for i, u in enumerate(uses) if "actions/setup-python" in u)
    assert poetry_idx < setup_py_idx


def test_second_generate_run_is_byte_identical(tmp_path: Path):
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["fastapi", "redis>=5", "pytest"]\n', encoding="utf-8"
    )
    ci = tmp_path / ".github" / "workflows" / "ci.yml"
    _generate(tmp_path)
    first = ci.read_text(encoding="utf-8")
    _generate(tmp_path)
    assert ci.read_text(encoding="utf-8") == first


def test_scan_and_check_reject_missing_or_non_directory_paths(tmp_path: Path):
    missing = tmp_path / "missing"
    a_file = tmp_path / "file.txt"
    a_file.write_text("hi", encoding="utf-8")
    def _flat(text: str) -> str:
        # Rich wraps long paths at the console width; compare whitespace-normalized output.
        return " ".join(text.split())

    for cmd in ("scan", "check", "generate"):
        res = runner.invoke(app, [cmd, "--path", str(missing)])
        assert res.exit_code == 1, (cmd, res.stdout)
        assert "does not exist" in _flat(res.stdout)
        res_file = runner.invoke(app, [cmd, "--path", str(a_file)])
        assert res_file.exit_code == 1, (cmd, res_file.stdout)
        assert "is not a directory" in _flat(res_file.stdout)
