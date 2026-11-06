"""
Python Language and Ecosystem Detector.
"""

from __future__ import annotations

import re
import tomllib
from typing import Optional
from heurix.core.context import LanguageContext, ProjectContext, ServiceRequirement
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


class PythonDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Python"

    def detect(self, indexer: RepoIndexer) -> bool:
        indicators = [
            "pyproject.toml",
            "requirements.txt",
            "Pipfile",
            "setup.py",
            "setup.cfg",
            ".python-version",
            "uv.lock",
            "poetry.lock",
        ]
        return any(indexer.has_file(f) for f in indicators) or bool(indexer.find_files("*.py"))

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Python ecosystem...")

        # 1. Determine Runtime Version
        runtime_version = "3.12"
        version_source = "default"

        if indexer.has_file(".python-version"):
            raw = indexer.read_text(".python-version") or ""
            match = re.search(r"(\d+\.\d+)", raw.strip())
            if match:
                runtime_version = match.group(1)
                version_source = ".python-version"
        elif indexer.has_file(".tool-versions"):
            raw = indexer.read_text(".tool-versions") or ""
            match = re.search(r"python\s+(\d+\.\d+)", raw)
            if match:
                runtime_version = match.group(1)
                version_source = ".tool-versions"
        elif indexer.has_file("pyproject.toml"):
            content = indexer.read_text("pyproject.toml") or ""
            try:
                data = tomllib.loads(content)
                req_python = (
                    data.get("project", {}).get("requires-python")
                    or data.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python")
                )
                if req_python:
                    match = re.search(r"(\d+\.\d+)", str(req_python))
                    if match:
                        runtime_version = match.group(1)
                        version_source = "pyproject.toml"
            except Exception:
                pass

        context.add_explain(f"Detected Python {runtime_version} (via {version_source})")

        # 2. Package Manager and Lockfile
        package_manager = "pip"
        install_cmd = "pip install -r requirements.txt"

        if indexer.has_file("uv.lock"):
            package_manager = "uv"
            install_cmd = "uv sync --frozen"
            context.add_explain("Detected Package Manager: uv (via uv.lock)")
        elif indexer.has_file("poetry.lock"):
            package_manager = "poetry"
            install_cmd = "poetry install --no-interaction"
            context.add_explain("Detected Package Manager: poetry (via poetry.lock)")
        elif indexer.has_file("Pipfile.lock") or indexer.has_file("Pipfile"):
            package_manager = "pipenv"
            install_cmd = "pipenv install --deploy"
            context.add_explain("Detected Package Manager: pipenv (via Pipfile)")
        elif indexer.has_file("requirements.txt"):
            package_manager = "pip"
            install_cmd = "pip install -r requirements.txt"
            context.add_explain("Detected Package Manager: pip (via requirements.txt)")
        elif indexer.has_file("pyproject.toml"):
            package_manager = "pip"
            install_cmd = "pip install ."
            context.add_explain("Detected Package Manager: pip (via pyproject.toml)")

        # 3. Framework & Dependency Scanning
        framework: Optional[str] = None
        deps_text = ""
        for fn in ["pyproject.toml", "requirements.txt", "Pipfile", "setup.py"]:
            c = indexer.read_text(fn)
            if c:
                deps_text += "\n" + c

        deps_lower = deps_text.lower()

        if "fastapi" in deps_lower:
            framework = "FastAPI"
        elif "django" in deps_lower:
            framework = "Django"
        elif "flask" in deps_lower:
            framework = "Flask"

        if framework:
            context.add_explain(f"Detected Framework: {framework}")

        # 4. Test Runner & Linter
        test_cmd = "pytest"
        if "pytest" in deps_lower or indexer.has_file("pytest.ini") or indexer.has_file("tests") or "[tool.pytest" in deps_text:
            test_cmd = "pytest"
            context.add_explain("Detected Test Runner: pytest")
        elif "django" in deps_lower and indexer.has_file("manage.py"):
            test_cmd = "python manage.py test"
            context.add_explain("Detected Test Runner: django manage.py test")
        else:
            test_cmd = "python -m unittest discover"

        lint_cmd = None
        if "ruff" in deps_lower or "[tool.ruff" in deps_text:
            lint_cmd = "ruff check ."
            context.add_explain("Detected Linter: ruff")
        elif "flake8" in deps_lower:
            lint_cmd = "flake8 ."
            context.add_explain("Detected Linter: flake8")

        # 5. Service Container Inference from dependencies
        if any(db in deps_lower for db in ["psycopg2", "asyncpg", "postgresql", "pgvector"]):
            if not any(s.name == "postgres" for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="postgres",
                        image="postgres:16-alpine",
                        ports=[5432],
                        env={
                            "POSTGRES_USER": "test_user",
                            "POSTGRES_PASSWORD": "test_password",
                            "POSTGRES_DB": "test_db",
                        },
                        source_file="python dependencies",
                    )
                )
                context.add_explain("Inferred Backing Service: PostgreSQL 16 (via python postgres client)")

        if any(r in deps_lower for r in ["redis", "aioredis", "celery"]):
            if not any(s.name == "redis" for s in context.services):
                context.services.append(
                    ServiceRequirement(
                        name="redis",
                        image="redis:7-alpine",
                        ports=[6379],
                        env={},
                        source_file="python dependencies",
                    )
                )
                context.add_explain("Inferred Backing Service: Redis 7 (via python redis client/celery)")

        context.languages.append(
            LanguageContext(
                language="python",
                runtime_version=runtime_version,
                version_source=version_source,
                package_manager=package_manager,
                install_cmd=install_cmd,
                test_cmd=test_cmd,
                lint_cmd=lint_cmd,
                framework=framework,
                confidence=0.98 if version_source != "default" else 0.85,
            )
        )
