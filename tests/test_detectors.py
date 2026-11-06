"""
Tests for language, framework, and infrastructure detectors.
"""

from __future__ import annotations

from pathlib import Path
from heurix.core.context import ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.docker_detector import DockerDetector
from heurix.detectors.env_detector import EnvDetector
from heurix.detectors.node_detector import NodeDetector
from heurix.detectors.python_detector import PythonDetector
from heurix.detectors.rust_detector import RustDetector


def test_python_detector_uv_and_postgres(tmp_path: Path):
    (tmp_path / ".python-version").write_text("3.12.3", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = [
    "fastapi",
    "psycopg2-binary",
    "pytest",
]
""",
        encoding="utf-8",
    )

    indexer = RepoIndexer(tmp_path)
    context = ProjectContext(repo_name="demo", repo_root=str(tmp_path))

    detector = PythonDetector()
    assert detector.detect(indexer)
    detector.analyze(indexer, context)

    assert len(context.languages) == 1
    py = context.languages[0]
    assert py.language == "python"
    assert py.runtime_version == "3.12"
    assert py.package_manager == "uv"
    assert py.install_cmd == "uv sync --frozen"
    assert py.framework == "FastAPI"
    assert py.test_cmd == "pytest"

    # Backing service inferred
    assert any(s.name == "postgres" for s in context.services)


def test_node_detector_pnpm_monorepo(tmp_path: Path):
    (tmp_path / ".nvmrc").write_text("v20.10.0\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        """{
        "name": "monorepo-root",
        "scripts": {
            "test": "vitest run",
            "build": "pnpm -r build"
        },
        "dependencies": {
            "ioredis": "^5.0.0"
        }
    }""",
        encoding="utf-8",
    )

    indexer = RepoIndexer(tmp_path)
    context = ProjectContext(repo_name="monorepo", repo_root=str(tmp_path))

    detector = NodeDetector()
    assert detector.detect(indexer)
    detector.analyze(indexer, context)

    assert context.is_monorepo is True
    assert len(context.languages) == 1
    node = context.languages[0]
    assert node.runtime_version == "20.x"
    assert node.package_manager == "pnpm"
    assert node.install_cmd == "pnpm i --frozen-lockfile"
    assert node.test_cmd == "pnpm test"

    # Backing service inferred
    assert any(s.name == "redis" for s in context.services)


def test_docker_and_env_detector(tmp_path: Path):
    (tmp_path / "Dockerfile").write_text(
        """
FROM python:3.12-slim
EXPOSE 8000
CMD ["uvicorn", "main:app"]
""",
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text(
        """
APP_ENV=production
DATABASE_URL=postgres://user:pass@localhost:5432/db
STRIPE_SECRET_KEY=sk_test_12345
API_TOKEN=xyz
""",
        encoding="utf-8",
    )

    indexer = RepoIndexer(tmp_path)
    context = ProjectContext(repo_name="app", repo_root=str(tmp_path))

    docker_det = DockerDetector()
    assert docker_det.detect(indexer)
    docker_det.analyze(indexer, context)

    assert len(context.containers) == 1
    assert context.containers[0].exposed_ports == [8000]

    env_det = EnvDetector()
    assert env_det.detect(indexer)
    env_det.analyze(indexer, context)

    assert "STRIPE_SECRET_KEY" in context.required_secrets
    assert "API_TOKEN" in context.required_secrets
    assert context.env_vars["APP_ENV"] == "production"
