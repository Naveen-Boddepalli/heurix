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


def test_framework_without_dockerfile_skips_kubernetes(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "flask\n")
    _write(tmp_path, "app.py", "x = 1\n")
    _generate(tmp_path)
    assert not (tmp_path / "k8s").exists()


def test_vercel_deploy_secrets_stay_out_of_kubernetes_secret(tmp_path: Path):
    _write(tmp_path, "package.json", json.dumps({"name": "web", "scripts": {"build": "next build"}, "dependencies": {"next": "15.0.0"}}))
    _write(tmp_path, "package-lock.json", "{}")
    _write(tmp_path, "vercel.json", '{"framework": "nextjs"}')
    _write(tmp_path, "Dockerfile", "FROM node:20\nEXPOSE 3000\n")
    _write(tmp_path, ".env.example", "API_TOKEN=\n")
    doc = _generate(tmp_path)
    assert "deploy_vercel" in doc["jobs"]
    secret = (tmp_path / "k8s" / "secret.yaml").read_text(encoding="utf-8")
    assert "API_TOKEN" in secret
    assert "VERCEL" not in secret


def test_init_leaves_kubernetes_off_when_repo_has_no_manifests(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "flask\n")
    _write(tmp_path, "app.py", "x = 1\n")
    _write(tmp_path, "Dockerfile", "FROM python:3.12\n")
    _generate(tmp_path, "--no-k8s")
    assert _invoke("init", "--path", str(tmp_path), "--no-hooks", "--yes").exit_code == 0
    assert "include_k8s = false" in (tmp_path / ".heurix.toml").read_text(encoding="utf-8")
    assert _invoke("check", "--path", str(tmp_path)).exit_code == 0


def test_init_keeps_kubernetes_on_when_manifests_exist(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "flask\n")
    _write(tmp_path, "app.py", "x = 1\n")
    _write(tmp_path, "Dockerfile", "FROM python:3.12\n")
    _generate(tmp_path)
    assert _invoke("init", "--path", str(tmp_path), "--no-hooks", "--yes").exit_code == 0
    assert "include_k8s = true" in (tmp_path / ".heurix.toml").read_text(encoding="utf-8")
