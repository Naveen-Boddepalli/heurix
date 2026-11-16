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


def test_monorepo_paths_filter_includes_root_files_and_workflow(tmp_path: Path):
    _write(tmp_path, "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
    _write(tmp_path, "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
    _write(tmp_path, "package.json", '{"name": "mono", "private": true}')
    for name in ("api", "web"):
        _write(tmp_path, f"apps/{name}/package.json", json.dumps({"name": name, "scripts": {"test": "vitest run"}}))
        _write(tmp_path, f"apps/{name}/index.ts", "export {}\n")
    paths = _generate(tmp_path, "--no-k8s")["on"]["push"]["paths"]
    assert paths[:2] == ["*", ".github/workflows/**"]
    assert "apps/api/**" in paths and "apps/web/**" in paths


def test_cargo_workspace_members_cache_shared_root_target(tmp_path: Path):
    _write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["crates/a", "crates/b"]\nresolver = "2"\n')
    for name in ("a", "b"):
        _write(tmp_path, f"crates/{name}/Cargo.toml", f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n')
        _write(tmp_path, f"crates/{name}/src/lib.rs", "pub fn f() {}\n")
    jobs = _generate(tmp_path, "--no-k8s")["jobs"]
    for job_id in ("test-crates-a", "test-crates-b"):
        cache = next(s for s in jobs[job_id]["steps"] if "rust-cache" in s.get("uses", ""))
        assert cache["with"]["workspaces"] == ". -> target"


def test_standalone_nested_crate_caches_its_own_target(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\n')
    _write(tmp_path, "app.py", "x = 1\n")
    _write(tmp_path, "native/Cargo.toml", '[package]\nname = "native"\nversion = "0.1.0"\nedition = "2021"\n')
    _write(tmp_path, "native/src/lib.rs", "pub fn f() {}\n")
    jobs = _generate(tmp_path, "--no-k8s")["jobs"]
    rust_job = next(j for j in jobs.values() if any("rust-cache" in s.get("uses", "") for s in j["steps"]))
    cache = next(s for s in rust_job["steps"] if "rust-cache" in s.get("uses", ""))
    assert cache["with"]["workspaces"] == "native -> target"


def _merge(existing: str, new: str):
    from heurix.core.merger import SmartMerger

    merger = SmartMerger()
    return merger, merger.merge_yaml(existing, new)


_NEW_WF = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.12']
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
      - name: Run tests (python)
        run: python -m pytest
"""


def test_inline_preserve_keeps_runs_on_and_strategy():
    existing = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-24.04  # @heurix:preserve pinned by SRE
    strategy:  # @heurix:preserve
      matrix:
        python-version: ['3.11', '3.12']
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
      - name: Run tests (python)
        run: python -m pytest
"""
    merger, out = _merge(existing, _NEW_WF)
    doc = YAML(typ="safe").load(out)
    assert doc["jobs"]["test"]["runs-on"] == "ubuntu-24.04"
    assert doc["jobs"]["test"]["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    assert merger.replaced == []


def test_replaced_user_values_are_reported():
    existing = _NEW_WF.replace("runs-on: ubuntu-latest", "runs-on: ubuntu-24.04").replace(
        "run: python -m pytest", "run: python -m pytest -x --cov"
    )
    merger, out = _merge(existing, _NEW_WF)
    assert "runs-on: ubuntu-latest" in out
    assert any("runs-on" in n and "ubuntu-24.04" in n for n in merger.replaced)
    assert any("Run tests (python)" in n and "-x --cov" in n for n in merger.replaced)


def test_unchanged_merge_reports_nothing():
    merger, out = _merge(_NEW_WF, _NEW_WF)
    assert merger.replaced == []


def test_generate_prints_replaced_values(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "pytest\n")
    _write(tmp_path, "app.py", "x = 1\n")
    _generate(tmp_path, "--no-k8s")
    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    wf.write_text(wf.read_text(encoding="utf-8").replace("run: python -m pytest", "run: python -m pytest -q"), encoding="utf-8")
    res = _invoke("generate", "--path", str(tmp_path), "--yes", "--no-k8s")
    assert res.exit_code == 0
    assert "will be replaced" in res.stdout
    assert "@heurix:preserve" in res.stdout


def test_preserve_directive_keeps_step_indentation():
    existing = _NEW_WF.replace(
        "      - name: Run tests (python)\n",
        "      # @heurix:preserve\n      - name: Upload coverage\n        run: echo cov\n      - name: Run tests (python)\n",
    )
    _, out = _merge(existing, _NEW_WF)
    assert "\n      # @heurix:preserve\n      - name: Upload coverage" in out


def test_malformed_package_json_is_reported(tmp_path: Path):
    _write(tmp_path, "package.json", '{"name": "x", "scripts": {')
    _write(tmp_path, "index.js", "x\n")
    res = _invoke("generate", "--path", str(tmp_path), "--yes", "--no-k8s", "--dry-run")
    assert res.exit_code == 0
    assert "Could not parse package.json" in res.stdout


def test_malformed_pyproject_is_reported_without_explain(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", "[project\nname=")
    _write(tmp_path, "a.py", "x = 1\n")
    res = _invoke("generate", "--path", str(tmp_path), "--yes", "--no-k8s", "--dry-run", "--no-explain")
    assert res.exit_code == 0
    assert "Could not parse pyproject.toml" in res.stdout


def test_check_fails_on_invalid_policy_file(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "pytest\n")
    _write(tmp_path, "app.py", "x = 1\n")
    _generate(tmp_path, "--no-k8s")
    _write(tmp_path, ".heurix.toml", "[engine]\nrunner = \n")
    res = _invoke("check", "--path", str(tmp_path))
    assert res.exit_code == 1
    assert "Invalid Policy" in res.stdout


def test_malformed_workflow_recommendation_names_real_options(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "pytest\n")
    _write(tmp_path, "app.py", "x = 1\n")
    _write(tmp_path, ".github/workflows/ci.yml", "jobs:\n  t:\n   x: [\n")
    res = _invoke("check", "--path", str(tmp_path))
    assert res.exit_code == 1
    assert "--force" not in res.stdout
    assert "non_destructive" in res.stdout


def test_check_flags_services_sharing_a_host_port(tmp_path: Path):
    _write(tmp_path, "uv.lock", "")
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\ndependencies = ["psycopg", "pytest"]\n')
    _write(tmp_path, "docker-compose.yml", "services:\n  db:\n    image: postgres:16\n")
    _generate(tmp_path, "--no-k8s")
    assert _invoke("check", "--path", str(tmp_path)).exit_code == 0

    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    text = wf.read_text(encoding="utf-8").replace(
        "    steps:\n",
        "      db:\n        image: postgres:16\n        ports:\n          - 5432:5432\n    steps:\n",
        1,
    )
    wf.write_text(text, encoding="utf-8")
    res = _invoke("check", "--path", str(tmp_path))
    assert res.exit_code == 1
    assert "host port 5432" in " ".join(res.stdout.split())


def test_service_host_port_parsing():
    from heurix.core.drift import _service_host_port

    assert _service_host_port("5432:5432") == "5432"
    assert _service_host_port("127.0.0.1:6380:6379") == "6380"
    assert _service_host_port("5432") is None
    assert _service_host_port(5432) is None
    assert _service_host_port("53:53/udp") == "53"
