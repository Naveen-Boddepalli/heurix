"""
Regression tests for usability and reliability issues found by running `hx` as
different kinds of users (beginner, frontend, monorepo, systems, DevOps).
"""

from __future__ import annotations

import json
from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from heurix.cli import app

runner = CliRunner()


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _invoke(*args: str):
    return runner.invoke(app, list(args))


def _generate(repo: Path, *extra: str) -> dict:
    res = _invoke("generate", "--path", str(repo), "--yes", "--non-interactive", *extra)
    assert res.exit_code == 0, res.stdout
    return YAML(typ="safe").load((repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _run_steps(job: dict) -> list:
    return [s["run"] for s in job["steps"] if "run" in s]


def test_flat_layout_python_uses_python_m_pytest(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "flask\npytest\n")
    _write(tmp_path, "app.py", "x = 1\n")
    _write(tmp_path, "tests/test_app.py", "from app import x\n\ndef test_x():\n    assert x == 1\n")
    job = _generate(tmp_path, "--no-k8s")["jobs"]["test"]
    assert "python -m pytest" in _run_steps(job)
