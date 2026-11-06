"""
Tests for YAML Synthesizers.
"""

from __future__ import annotations

from heurix.core.context import ContainerContext, LanguageContext, ProjectContext, ServiceRequirement
from heurix.synthesizers.github_actions import GitHubActionsSynthesizer
from heurix.synthesizers.kubernetes import KubernetesSynthesizer
from heurix.synthesizers.maintenance import MaintenanceSynthesizer


def test_github_actions_synthesizer():
    context = ProjectContext(
        repo_name="demo-app",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="uv",
                install_cmd="uv sync --frozen",
                test_cmd="pytest",
                lint_cmd="ruff check .",
            )
        ],
        services=[
            ServiceRequirement(
                name="postgres",
                image="postgres:16-alpine",
                ports=[5432],
                env={"POSTGRES_PASSWORD": "test"},
                source_file="pyproject.toml",
            )
        ],
        required_secrets=["DATABASE_URL"],
        env_vars={"APP_ENV": "test"},
    )

    syn = GitHubActionsSynthesizer()
    res = syn.synthesize(context)

    assert ".github/workflows/ci.yml" in res
    content = res[".github/workflows/ci.yml"]

    assert "actions/checkout@v4" in content
    assert "astral-sh/setup-uv@v5" in content
    assert "python-version: '3.12'" in content or 'python-version: "3.12"' in content or "python-version: 3.12" in content
    assert "uv sync --frozen" in content
    assert "ruff check ." in content
    assert "pytest" in content
    assert "postgres:16-alpine" in content
    assert "${{ secrets.DATABASE_URL }}" in content


def test_dependabot_synthesizer():
    context = ProjectContext(
        repo_name="demo-app",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="pnpm",
                install_cmd="pnpm i --frozen-lockfile",
            )
        ],
        containers=[ContainerContext(dockerfile_path="Dockerfile")],
    )

    syn = MaintenanceSynthesizer()
    res = syn.synthesize(context)

    assert ".github/dependabot.yml" in res
    content = res[".github/dependabot.yml"]
    assert "package-ecosystem: github-actions" in content
    assert "package-ecosystem: npm" in content
    assert "package-ecosystem: docker" in content


def test_kubernetes_synthesizer():
    context = ProjectContext(
        repo_name="my_api",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                framework="FastAPI",
            )
        ],
        containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
    )

    syn = KubernetesSynthesizer()
    res = syn.synthesize(context)

    assert "k8s/deployment.yaml" in res
    assert "k8s/service.yaml" in res
    assert "k8s/ingress.yaml" in res

    dep = res["k8s/deployment.yaml"]
    assert "containerPort: 8000" in dep
    assert "app: my-api" in dep
