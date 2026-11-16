"""
Regression tests for backing-service reconciliation.

Covers repos where dependency inference and docker-compose both describe the same
database, which used to produce two containers on one host port, and compose-only
Postgres services that the official image would refuse to start.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from heurix.cli import app
from heurix.core.context import ServiceRequirement
from heurix.detectors.service_reconciler import resolve_compose_value, service_kind

runner = CliRunner()


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _generate(repo: Path) -> dict:
    res = runner.invoke(app, ["generate", "--path", str(repo), "--yes", "--non-interactive", "--no-k8s"])
    assert res.exit_code == 0, res.stdout
    return YAML(typ="safe").load((repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _python_repo(root: Path, deps: str) -> None:
    _write(root, "uv.lock", "")
    _write(root, "pyproject.toml", f'[project]\nname = "svc"\ndependencies = [{deps}]\n')
    _write(root, "tests/test_x.py", "def test_x():\n    assert True\n")


def _host_ports(job: dict) -> list:
    return [p.split(":")[0] for svc in (job.get("services") or {}).values() for p in svc.get("ports", [])]


def _assert_db_url_matches_service(job: dict) -> None:
    pg = next(s for s in job["services"].values() if "postgres" in s["image"])
    url = next(
        step["env"]["DATABASE_URL"]
        for step in job["steps"]
        if "DATABASE_URL" in (step.get("env") or {})
    )
    parsed = urlparse(url)
    assert parsed.username == pg["env"]["POSTGRES_USER"]
    assert parsed.password == pg["env"]["POSTGRES_PASSWORD"]
    assert parsed.path.lstrip("/") == pg["env"]["POSTGRES_DB"]


def test_dependency_and_compose_services_are_merged(tmp_path: Path):
    _python_repo(tmp_path, '"psycopg[binary]>=3.1", "redis>=5", "pytest"')
    _write(tmp_path, ".env.example", "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app\n")
    _write(
        tmp_path,
        "docker-compose.yml",
        "services:\n"
        "  db:\n    image: postgres:16\n    ports: ['5433:5432']\n"
        "  cache:\n    image: redis:7\n    ports: ['6379:6379']\n",
    )
    job = _generate(tmp_path)["jobs"]["test"]

    assert set(job["services"]) == {"postgres", "redis"}
    assert job["services"]["postgres"]["image"] == "postgres:16"
    assert job["services"]["redis"]["image"] == "redis:7"
    ports = _host_ports(job)
    assert len(ports) == len(set(ports)), f"host ports collide: {ports}"
    _assert_db_url_matches_service(job)


def test_compose_only_postgres_gets_credentials_matching_database_url(tmp_path: Path):
    _python_repo(tmp_path, '"fastapi", "pytest"')
    _write(tmp_path, ".env.example", "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/app\n")
    _write(tmp_path, "docker-compose.yml", "services:\n  db:\n    image: postgres:16\n")
    job = _generate(tmp_path)["jobs"]["test"]

    db = job["services"]["db"]
    assert db["env"]["POSTGRES_PASSWORD"]
    assert db["ports"] == ["5432:5432"]
    _assert_db_url_matches_service(job)


def test_compose_interpolation_and_empty_password_are_resolved(tmp_path: Path):
    _python_repo(tmp_path, '"fastapi", "pytest"')
    _write(tmp_path, ".env.example", "DATABASE_URL=postgresql://u:p@localhost:5432/x\n")
    _write(
        tmp_path,
        "docker-compose.yml",
        "services:\n  db:\n    image: postgres:16\n    environment:\n"
        "      POSTGRES_USER: ${DB_USER:-appuser}\n"
        "      POSTGRES_PASSWORD: ${DB_PASSWORD:-}\n"
        "      POSTGRES_DB: appdb\n",
    )
    job = _generate(tmp_path)["jobs"]["test"]

    env = job["services"]["db"]["env"]
    assert env["POSTGRES_USER"] == "appuser"
    assert env["POSTGRES_DB"] == "appdb"
    assert env["POSTGRES_PASSWORD"] and "$" not in env["POSTGRES_PASSWORD"]
    _assert_db_url_matches_service(job)


def test_two_compose_postgres_services_collapse_to_one(tmp_path: Path):
    _python_repo(tmp_path, '"fastapi", "pytest"')
    _write(
        tmp_path,
        "docker-compose.yml",
        "services:\n"
        "  db:\n    image: postgres:16\n    environment:\n      POSTGRES_PASSWORD: pw\n"
        "  db_test:\n    image: pgvector/pgvector:pg16\n    ports: ['5434:5432']\n",
    )
    job = _generate(tmp_path)["jobs"]["test"]
    assert list(job["services"]) == ["db"]


def test_monorepo_merge_keeps_package_scoping(tmp_path: Path):
    _write(tmp_path, "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
    _write(tmp_path, "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
    _write(tmp_path, "package.json", '{"name": "mono", "private": true}')
    _write(
        tmp_path,
        "apps/api/package.json",
        '{"name": "api", "scripts": {"test": "jest"}, "dependencies": {"ioredis": "5.4.0"}}',
    )
    _write(tmp_path, "apps/api/index.ts", "export {}\n")
    _write(tmp_path, "apps/web/package.json", '{"name": "web", "scripts": {"test": "vitest run"}}')
    _write(tmp_path, "apps/web/index.ts", "export {}\n")
    _write(tmp_path, "docker-compose.yml", "services:\n  cache:\n    image: redis:7\n")
    jobs = _generate(tmp_path)["jobs"]

    assert jobs["test-apps-api"]["services"] == {
        "redis": {
            "image": "redis:7",
            "ports": ["6379:6379"],
            "options": jobs["test-apps-api"]["services"]["redis"]["options"],
        }
    }
    assert not jobs["test-apps-web"].get("services")


def test_regenerate_removes_stale_duplicate_services(tmp_path: Path):
    _python_repo(tmp_path, '"psycopg[binary]>=3.1", "pytest"')
    _write(tmp_path, "docker-compose.yml", "services:\n  db:\n    image: postgres:16\n")
    _write(
        tmp_path,
        ".github/workflows/ci.yml",
        "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    services:\n"
        "      postgres:\n        image: postgres:16-alpine\n        ports: ['5432:5432']\n"
        "      db:\n        image: postgres:16\n        ports: ['5432:5432']\n"
        "    steps:\n      - run: echo hi\n",
    )
    job = _generate(tmp_path)["jobs"]["test"]
    assert list(job["services"]) == ["postgres"]


@pytest.mark.parametrize(
    ("image", "name", "kind"),
    [
        ("postgres:16", "db", "postgres"),
        ("docker.io/library/postgres:16-alpine", "x", "postgres"),
        ("localhost:5000/pgvector/pgvector:pg16", "x", "postgres"),
        ("timescale/timescaledb:latest-pg16", "x", "postgres"),
        ("valkey/valkey:8", "cache", "redis"),
        ("mongo@sha256:abc", "x", "mongodb"),
        ("custom/thing:1", "redis", "redis"),
        ("nginx:1.27", "web", None),
    ],
)
def test_service_kind(image: str, name: str, kind):
    assert service_kind(ServiceRequirement(name=name, image=image)) == kind


@pytest.mark.parametrize(
    ("raw", "resolved"),
    [
        ("plain", "plain"),
        ("${A:-fallback}", "fallback"),
        ("${A-fallback}", "fallback"),
        ("${A:-}", ""),
        ("${A}", None),
        ("$A", None),
    ],
)
def test_resolve_compose_value(raw: str, resolved):
    assert resolve_compose_value(raw) == resolved
