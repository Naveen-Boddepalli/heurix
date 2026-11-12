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
    assert py.test_cmd == "uv run pytest"

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


def test_cpp_detector_makefile_no_cpp(tmp_path: Path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    indexer = RepoIndexer(tmp_path)
    from heurix.detectors.cpp_detector import CppDetector
    detector = CppDetector()
    # Must NOT detect C++ when only a generic Makefile is present without C/C++ files
    assert not detector.detect(indexer)

    # Adding a C++ source file should cause detection
    (tmp_path / "main.cpp").write_text("int main() { return 0; }", encoding="utf-8")
    indexer2 = RepoIndexer(tmp_path)
    assert detector.detect(indexer2)


def test_cpp_detector_cmake_standard(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\nproject(demo)\nset(CMAKE_CXX_STANDARD 17)\n",
        encoding="utf-8",
    )
    indexer = RepoIndexer(tmp_path)
    from heurix.detectors.cpp_detector import CppDetector
    detector = CppDetector()
    assert detector.detect(indexer)

    context = ProjectContext(repo_name="demo", repo_root=str(tmp_path))
    detector.analyze(indexer, context)
    assert len(context.languages) == 1
    cpp = context.languages[0]
    assert cpp.language == "cpp"
    assert cpp.runtime_version == "c++17"
    assert cpp.version_source == "CMakeLists.txt"


def test_docker_detector_skips_local_build_service(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text(
        """
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8000:8000"
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
""",
        encoding="utf-8",
    )
    indexer = RepoIndexer(tmp_path)
    context = ProjectContext(repo_name="demo", repo_root=str(tmp_path))

    detector = DockerDetector()
    assert detector.detect(indexer)
    detector.analyze(indexer, context)

    # Only postgres should be added to services; app (local build container) must be skipped
    service_names = [s.name for s in context.services]
    assert "postgres" in service_names
    assert "app" not in service_names


def test_docker_detector_multistage_dockerfile(tmp_path: Path):
    (tmp_path / "Dockerfile").write_text(
        """
FROM golang:1.21 AS builder
WORKDIR /app
COPY . .
RUN go build -o main .

FROM alpine:3.19
COPY --from=builder /app/main /main
EXPOSE 8080
CMD ["/main"]
""",
        encoding="utf-8",
    )
    indexer = RepoIndexer(tmp_path)
    context = ProjectContext(repo_name="demo", repo_root=str(tmp_path))

    detector = DockerDetector()
    assert detector.detect(indexer)
    detector.analyze(indexer, context)

    assert len(context.containers) == 1
    container = context.containers[0]
    assert container.base_image == "alpine:3.19"
    assert container.exposed_ports == [8080]


def test_python_detector_streamlit_and_poetry(tmp_path: Path):
    (tmp_path / "poetry.lock").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.poetry]
name = "streamlit-app"
version = "0.1.0"
[tool.poetry.dependencies]
python = "^3.11"
streamlit = "^1.28.0"
pytest = "^7.0.0"
ruff = "^0.1.0"
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
    assert py.framework == "Streamlit"
    assert py.package_manager == "poetry"
    assert py.install_cmd == "poetry install --no-interaction"
    assert py.test_cmd == "poetry run pytest"
    assert py.lint_cmd == "poetry run ruff check ."


def test_python_detector_bare_py_repo(tmp_path: Path):
    (tmp_path / "script.py").write_text("print('hello')\n", encoding="utf-8")
    indexer = RepoIndexer(tmp_path)
    detector = PythonDetector()
    assert detector.detect(indexer)
    context = ProjectContext(repo_name="bare", repo_root=str(tmp_path))
    detector.analyze(indexer, context)
    assert len(context.languages) == 1
    py = context.languages[0]
    assert py.install_cmd == "python -m pip install --upgrade pip"
    assert "requirements.txt" not in py.install_cmd


def test_cpp_detector_clang_tidy_guarded(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("project(demo)\n", encoding="utf-8")
    indexer = RepoIndexer(tmp_path)
    from heurix.detectors.cpp_detector import CppDetector
    detector = CppDetector()
    context = ProjectContext(repo_name="demo", repo_root=str(tmp_path))
    detector.analyze(indexer, context)
    assert context.languages[0].lint_cmd is None

    # Now add .clang-tidy
    (tmp_path / ".clang-tidy").write_text("Checks: '*'\n", encoding="utf-8")
    indexer2 = RepoIndexer(tmp_path)
    context2 = ProjectContext(repo_name="demo", repo_root=str(tmp_path))
    detector.analyze(indexer2, context2)
    assert context2.languages[0].lint_cmd == "clang-tidy -p build"


def test_cloud_detector_vercel(tmp_path: Path):
    (tmp_path / "vercel.json").write_text(
        """{
        "name": "my-web-app",
        "framework": "nextjs",
        "buildCommand": "pnpm build",
        "outputDirectory": ".next"
    }""",
        encoding="utf-8",
    )
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "hello.ts").write_text("export default function handler() {}", encoding="utf-8")

    from heurix.detectors.cloud_detector import CloudDetector
    detector = CloudDetector()
    indexer = RepoIndexer(tmp_path)
    assert detector.detect(indexer)

    context = ProjectContext(repo_name="my-web-app", repo_root=str(tmp_path))
    detector.analyze(indexer, context)

    assert len(context.deployment_targets) == 1
    target = context.deployment_targets[0]
    assert target.platform == "vercel"
    assert target.project_id == "my-web-app"
    assert "hosting" in target.features
    assert "serverless" in target.features
    assert "VERCEL_TOKEN" in context.required_secrets
    assert "VERCEL_ORG_ID" in context.required_secrets
    assert "VERCEL_PROJECT_ID" in context.required_secrets


def test_cloud_detector_firebase(tmp_path: Path):
    (tmp_path / ".firebaserc").write_text(
        """{
        "projects": {
            "default": "my-firebase-prod"
        }
    }""",
        encoding="utf-8",
    )
    (tmp_path / "firebase.json").write_text(
        """{
        "hosting": {
            "public": "dist",
            "rewrites": [{"source": "**", "destination": "/index.html"}]
        },
        "firestore": {
            "rules": "firestore.rules"
        },
        "functions": {
            "source": "functions"
        }
    }""",
        encoding="utf-8",
    )

    from heurix.detectors.cloud_detector import CloudDetector
    detector = CloudDetector()
    indexer = RepoIndexer(tmp_path)
    assert detector.detect(indexer)

    context = ProjectContext(repo_name="app", repo_root=str(tmp_path))
    detector.analyze(indexer, context)

    assert len(context.deployment_targets) == 1
    target = context.deployment_targets[0]
    assert target.platform == "firebase"
    assert target.project_id == "my-firebase-prod"
    assert "hosting" in target.features
    assert "firestore" in target.features
    assert "functions" in target.features
    assert "FIREBASE_SERVICE_ACCOUNT" in context.required_secrets
    assert target.deploy_cmd == "firebase deploy"


def test_docker_port_extraction_helper_formats():
    from heurix.detectors.docker_detector import extract_container_ports

    assert extract_container_ports(80) == [80]
    assert extract_container_ports("80") == [80]
    assert extract_container_ports("80/udp") == [80]
    assert extract_container_ports("8080:80") == [80]
    assert extract_container_ports("8080:80/tcp") == [80]
    assert extract_container_ports("127.0.0.1:8080:80") == [80]
    assert extract_container_ports("0.0.0.0:8080:80/tcp") == [80]
    assert extract_container_ports("127.0.0.1::80") == [80]
    assert extract_container_ports("[::1]:8080:80/tcp") == [80]
    assert extract_container_ports("3000-3002") == [3000, 3001, 3002]
    assert extract_container_ports("3000-3002:4000-4002") == [4000, 4001, 4002]
    assert extract_container_ports("127.0.0.1:3000-3002:4000-4002/udp") == [4000, 4001, 4002]
    assert extract_container_ports({"target": 80, "published": 8080}) == [80]
    assert extract_container_ports({"target": "5432", "published": 15432}) == [5432]


def test_docker_port_validation_bounds():
    from heurix.detectors.docker_detector import extract_container_ports

    assert extract_container_ports(0) == []
    assert extract_container_ports(65536) == []
    assert extract_container_ports(-80) == []
    assert extract_container_ports(True) == []
    assert extract_container_ports("") == []
    assert extract_container_ports("invalid") == []
    assert extract_container_ports("4005-4000") == []
    assert extract_container_ports("0-5") == []
    assert extract_container_ports("65530-65540") == []
    assert extract_container_ports({"published": 8080}) == []
    assert extract_container_ports({"target": 0}) == []
    assert extract_container_ports({"target": 70000}) == []
    assert extract_container_ports({"target": True}) == []


def test_docker_port_compose_integration(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text(
        """
version: '3.8'
services:
  db:
    image: postgres:16-alpine
    ports:
      - "15432:5432"
  cache:
    image: redis:7-alpine
    ports:
      - 6379
  web:
    image: nginx:alpine
    ports:
      - "127.0.0.1:8080:80"
      - "0.0.0.0:8443:443/tcp"
      - "3000-3002:4000-4002"
      - target: 9000
        published: 19000
        protocol: tcp
""",
        encoding="utf-8",
    )

    indexer = RepoIndexer(tmp_path)
    context = ProjectContext(repo_name="demo", repo_root=str(tmp_path))
    detector = DockerDetector()
    detector.analyze(indexer, context)

    by_name = {s.name: s for s in context.services}
    assert by_name["db"].ports == [5432]
    assert by_name["cache"].ports == [6379]
    assert by_name["web"].ports == [80, 443, 4000, 4001, 4002, 9000]


def test_mock_service_python_exclusion(tmp_path: Path):
    # 1. Purely mock packages (fakeredis, testing.postgresql) must NOT trigger services
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    (repo1 / "requirements.txt").write_text(
        "fastapi\nfakeredis>=2.20\ntesting.postgresql==1.3.0\npytest\n",
        encoding="utf-8",
    )
    ctx1 = ProjectContext(repo_name="repo1", repo_root=str(repo1))
    PythonDetector().analyze(RepoIndexer(repo1), ctx1)
    assert ctx1.services == []

    # 2. mockredispy, pgmock, and fakeredis[aioredis] extras must NOT trigger services
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    (repo2 / "pyproject.toml").write_text(
        '[project]\nname="r2"\ndependencies=["mockredispy", "pgmock", "fakeredis[aioredis]"]\n',
        encoding="utf-8",
    )
    ctx2 = ProjectContext(repo_name="repo2", repo_root=str(repo2))
    PythonDetector().analyze(RepoIndexer(repo2), ctx2)
    assert ctx2.services == []

    # 3. Real postgres + mock redis -> only postgres inferred
    repo3 = tmp_path / "repo3"
    repo3.mkdir()
    (repo3 / "requirements.txt").write_text("psycopg2-binary\nfakeredis\n", encoding="utf-8")
    ctx3 = ProjectContext(repo_name="repo3", repo_root=str(repo3))
    PythonDetector().analyze(RepoIndexer(repo3), ctx3)
    assert [s.name for s in ctx3.services] == ["postgres"]

    # 4. Real redis alongside fakeredis -> redis inferred (not purely mocks)
    repo4 = tmp_path / "repo4"
    repo4.mkdir()
    (repo4 / "requirements.txt").write_text("redis>=5.0.0\nfakeredis>=2.20\n", encoding="utf-8")
    ctx4 = ProjectContext(repo_name="repo4", repo_root=str(repo4))
    PythonDetector().analyze(RepoIndexer(repo4), ctx4)
    assert [s.name for s in ctx4.services] == ["redis"]


def test_mock_service_node_exclusion(tmp_path: Path):
    # 1. Mock-only redis and postgres packages must NOT trigger services
    repo1 = tmp_path / "node1"
    repo1.mkdir()
    (repo1 / "package.json").write_text(
        '{"name":"n1","dependencies":{"express":"^4.18.0"},"devDependencies":{"redis-mock":"^0.56.3","ioredis-mock":"^8.9.0","pg-mem":"^2.6.0"}}',
        encoding="utf-8",
    )
    ctx1 = ProjectContext(repo_name="node1", repo_root=str(repo1))
    NodeDetector().analyze(RepoIndexer(repo1), ctx1)
    assert ctx1.services == []

    # 2. Prisma with sqlite3 and schema.prisma sqlite provider must NOT trigger postgres
    repo2 = tmp_path / "node2"
    (repo2 / "prisma").mkdir(parents=True)
    (repo2 / "package.json").write_text(
        '{"name":"n2","dependencies":{"@prisma/client":"^5.0.0","prisma":"^5.0.0","sqlite3":"^5.1.0"}}',
        encoding="utf-8",
    )
    (repo2 / "prisma" / "schema.prisma").write_text(
        'datasource db {\n  provider = "sqlite"\n  url = "file:./dev.db"\n}\n',
        encoding="utf-8",
    )
    ctx2 = ProjectContext(repo_name="node2", repo_root=str(repo2))
    NodeDetector().analyze(RepoIndexer(repo2), ctx2)
    assert ctx2.services == []

    # 3. TypeORM with sqlite3 must NOT trigger postgres
    repo3 = tmp_path / "node3"
    repo3.mkdir()
    (repo3 / "package.json").write_text(
        '{"name":"n3","dependencies":{"typeorm":"^0.3.0","sqlite3":"^5.1.0"}}',
        encoding="utf-8",
    )
    ctx3 = ProjectContext(repo_name="node3", repo_root=str(repo3))
    NodeDetector().analyze(RepoIndexer(repo3), ctx3)
    assert ctx3.services == []

    # 4. Prisma without verified backing adapter must NOT trigger postgres
    repo4 = tmp_path / "node4"
    repo4.mkdir()
    (repo4 / "package.json").write_text(
        '{"name":"n4","dependencies":{"prisma":"^5.0.0"}}',
        encoding="utf-8",
    )
    ctx4 = ProjectContext(repo_name="node4", repo_root=str(repo4))
    NodeDetector().analyze(RepoIndexer(repo4), ctx4)
    assert ctx4.services == []

    # 5. Prisma with postgresql schema.prisma MUST trigger postgres
    repo5 = tmp_path / "node5"
    (repo5 / "prisma").mkdir(parents=True)
    (repo5 / "package.json").write_text(
        '{"name":"n5","dependencies":{"@prisma/client":"^5.0.0"}}',
        encoding="utf-8",
    )
    (repo5 / "prisma" / "schema.prisma").write_text(
        'generator client {\n  provider = "prisma-client-js"\n}\ndatasource db {\n  provider = "postgresql"\n  url = env("DATABASE_URL")\n}\n',
        encoding="utf-8",
    )
    ctx5 = ProjectContext(repo_name="node5", repo_root=str(repo5))
    NodeDetector().analyze(RepoIndexer(repo5), ctx5)
    assert [s.name for s in ctx5.services] == ["postgres"]

    # 6. TypeORM + pg and real redis alongside redis-mock MUST trigger postgres and redis
    repo6 = tmp_path / "node6"
    repo6.mkdir()
    (repo6 / "package.json").write_text(
        '{"name":"n6","dependencies":{"typeorm":"^0.3.0","pg":"^8.11.0","redis":"^4.6.0"},"devDependencies":{"redis-mock":"^0.56.3"}}',
        encoding="utf-8",
    )
    ctx6 = ProjectContext(repo_name="node6", repo_root=str(repo6))
    NodeDetector().analyze(RepoIndexer(repo6), ctx6)
    assert {s.name for s in ctx6.services} == {"postgres", "redis"}


def test_sensitive_keywords_and_role_partitioning(tmp_path: Path):
    from heurix.detectors.env_detector import SENSITIVE_KEYWORDS

    for kw in ["URL", "URI", "DSN", "CONN", "WEBHOOK", "SESSION"]:
        assert kw in SENSITIVE_KEYWORDS

    (tmp_path / ".env.example").write_text(
        """
APP_ENV=staging
LOG_LEVEL=info
DATABASE_URL=postgres://user:pass@localhost:5432/db
API_URI=https://secret-api.internal/v1
SENTRY_DSN=https://key@sentry.io/123
DB_CONN_STRING=Server=myServer;Database=myDB;
STRIPE_WEBHOOK=whsec_abc
SESSION_ID_SALT=salty
VERCEL_TOKEN=vercel_tok
FIREBASE_SERVICE_ACCOUNT={"type":"service_account"}
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
DOCKER_PASSWORD=docker_pass
""",
        encoding="utf-8",
    )

    indexer = RepoIndexer(tmp_path)
    context = ProjectContext(repo_name="sec-app", repo_root=str(tmp_path))
    detector = EnvDetector()
    assert detector.detect(indexer)
    detector.analyze(indexer, context)

    # Non-sensitive defaults only
    assert context.env_vars == {"APP_ENV": "staging", "LOG_LEVEL": "info"}

    expected_test = {
        "DATABASE_URL",
        "API_URI",
        "SENTRY_DSN",
        "DB_CONN_STRING",
        "STRIPE_WEBHOOK",
        "SESSION_ID_SALT",
    }
    expected_deploy = {
        "VERCEL_TOKEN",
        "FIREBASE_SERVICE_ACCOUNT",
        "AWS_ACCESS_KEY_ID",
        "DOCKER_PASSWORD",
    }

    assert set(context.test_secrets) == expected_test
    assert set(context.deployment_secrets) == expected_deploy
    assert set(context.required_secrets) == (expected_test | expected_deploy)
    assert set(context.test_secrets).isdisjoint(set(context.deployment_secrets))


def test_workspace_topology_pnpm_and_npm_subpackages(tmp_path: Path):
    # 1. pnpm workspace with root coordinator, inherited lockfile, ! exclusion, and scoped service
    pnpm_repo = tmp_path / "pnpm_repo"
    (pnpm_repo / "apps" / "web").mkdir(parents=True)
    (pnpm_repo / "packages" / "ui" / "button").mkdir(parents=True)
    (pnpm_repo / "packages" / "test" / "ignored").mkdir(parents=True)
    (pnpm_repo / "site").mkdir(parents=True)

    (pnpm_repo / ".nvmrc").write_text("v20.11.0\n", encoding="utf-8")
    (pnpm_repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (pnpm_repo / "pnpm-workspace.yaml").write_text(
        "packages:\n  - './apps/*'\n  - 'packages/**'\n  - '!**/test/**'\n",
        encoding="utf-8",
    )
    (pnpm_repo / "package.json").write_text('{"name": "root", "private": true}', encoding="utf-8")
    (pnpm_repo / "apps" / "web" / "package.json").write_text(
        """{
        "name": "@acme/web",
        "scripts": {"build": "next build", "test": "vitest run", "lint": "eslint ."},
        "dependencies": {"next": "^14.0.0", "pg": "^8.11.0"}
    }""",
        encoding="utf-8",
    )
    (pnpm_repo / "packages" / "ui" / "button" / "package.json").write_text(
        """{
        "name": "@acme/button",
        "scripts": {"build": "vite build", "test": "vitest run"},
        "devDependencies": {"vite": "^5.0.0"}
    }""",
        encoding="utf-8",
    )
    (pnpm_repo / "packages" / "test" / "ignored" / "package.json").write_text(
        '{"name": "ignored"}',
        encoding="utf-8",
    )
    (pnpm_repo / "site" / "package.json").write_text('{"name": "docs-site"}', encoding="utf-8")

    indexer = RepoIndexer(pnpm_repo)
    ctx = ProjectContext(repo_name="pnpm_repo", repo_root=str(pnpm_repo))
    detector = NodeDetector()
    assert detector.detect(indexer)
    detector.analyze(indexer, ctx)

    assert ctx.is_monorepo is True
    root_node = ctx.get_language("node")
    assert root_node is not None
    assert root_node.working_dir == "."
    assert root_node.is_workspace_root is True

    pkg_by_path = {pkg.path: pkg for pkg in ctx.monorepo_packages}
    assert sorted(pkg_by_path.keys()) == ["apps/web", "packages/ui/button"]

    web = pkg_by_path["apps/web"]
    assert web.language == "node"
    assert web.package_manager == "pnpm"
    assert web.runtime_version == "20.x"
    assert web.install_cmd == "pnpm i --frozen-lockfile"
    assert web.build_cmd == "pnpm run build"
    assert web.test_cmd == "pnpm test"
    assert web.lint_cmd == "pnpm run lint"
    assert web.framework == "Next.js"
    assert web.cache_dependency_path == "pnpm-lock.yaml"

    btn = pkg_by_path["packages/ui/button"]
    assert btn.framework == "Vite"
    assert btn.cache_dependency_path == "pnpm-lock.yaml"

    pg_services = [s for s in ctx.services if s.name == "postgres"]
    assert len(pg_services) == 1
    assert pg_services[0].package_path == "apps/web"

    # 2. Yarn/npm object workspaces + turbo.json + local sub-package lockfile override
    npm_repo = tmp_path / "npm_repo"
    (npm_repo / "apps" / "admin").mkdir(parents=True)
    (npm_repo / "turbo.json").write_text('{"pipeline": {}}', encoding="utf-8")
    (npm_repo / "package-lock.json").write_text("{}", encoding="utf-8")
    (npm_repo / "package.json").write_text(
        '{"name": "npm-ws", "workspaces": {"packages": ["apps/*"]}}',
        encoding="utf-8",
    )
    (npm_repo / "apps" / "admin" / "package-lock.json").write_text("{}", encoding="utf-8")
    (npm_repo / "apps" / "admin" / "package.json").write_text(
        '{"name": "admin", "scripts": {"test": "jest"}, "dependencies": {"express": "^4.18.0", "redis": "^4.6.0"}}',
        encoding="utf-8",
    )

    npm_ctx = ProjectContext(repo_name="npm_repo", repo_root=str(npm_repo))
    detector.analyze(RepoIndexer(npm_repo), npm_ctx)
    assert npm_ctx.is_monorepo is True
    assert npm_ctx.get_language("node").is_workspace_root is True
    assert len(npm_ctx.monorepo_packages) == 1
    admin = npm_ctx.monorepo_packages[0]
    assert admin.path == "apps/admin"
    assert admin.package_manager == "npm"
    assert admin.install_cmd == "npm ci"
    assert admin.test_cmd == "npm test"
    assert admin.framework == "Express"
    assert admin.cache_dependency_path == "apps/admin/package-lock.json"
    assert [s.package_path for s in npm_ctx.services if s.name == "redis"] == ["apps/admin"]

    # 3. Sub-package without root package.json -> detect() True, representative LanguageContext is_workspace_root is None
    sub_only = tmp_path / "node_sub_only"
    (sub_only / "apps" / "web").mkdir(parents=True)
    (sub_only / "apps" / "web" / ".nvmrc").write_text("22.0.0\n", encoding="utf-8")
    (sub_only / "apps" / "web" / "package-lock.json").write_text("{}", encoding="utf-8")
    (sub_only / "apps" / "web" / "package.json").write_text('{"name": "web"}', encoding="utf-8")

    sub_indexer = RepoIndexer(sub_only)
    assert detector.detect(sub_indexer) is True
    sub_ctx = ProjectContext(repo_name="node_sub_only", repo_root=str(sub_only))
    detector.analyze(sub_indexer, sub_ctx)
    assert len(sub_ctx.monorepo_packages) == 1
    assert sub_ctx.monorepo_packages[0].runtime_version == "22.x"
    assert sub_ctx.monorepo_packages[0].cache_dependency_path == "apps/web/package-lock.json"
    rep = sub_ctx.get_language("node")
    assert rep is not None
    assert rep.is_workspace_root is None

    # 4. Active non-coordinator root package.json + heuristic sub-package -> root has is_workspace_root=False
    active_root = tmp_path / "active_root"
    (active_root / "tools" / "cli").mkdir(parents=True)
    (active_root / "package.json").write_text('{"name": "root-app", "scripts": {"test": "node test.js"}}', encoding="utf-8")
    (active_root / "tools" / "cli" / "package.json").write_text('{"name": "cli"}', encoding="utf-8")

    active_ctx = ProjectContext(repo_name="active_root", repo_root=str(active_root))
    detector.analyze(RepoIndexer(active_root), active_ctx)
    assert active_ctx.get_language("node").working_dir == "."
    assert active_ctx.get_language("node").is_workspace_root is False
    assert [p.path for p in active_ctx.monorepo_packages] == ["tools/cli"]


def test_workspace_topology_python_subpackages_and_docs_guard(tmp_path: Path):
    detector = PythonDetector()

    # 1. Pure docs/requirements.txt must NOT trigger PythonDetector
    docs_only = tmp_path / "docs_only"
    (docs_only / "docs").mkdir(parents=True)
    (docs_only / "docs" / "requirements.txt").write_text("sphinx\n", encoding="utf-8")
    assert detector.detect(RepoIndexer(docs_only)) is False

    # 2. Sub-packages without root Python manifest; docs/requirements.txt ignored cleanly
    mono = tmp_path / "py_mono"
    (mono / "docs").mkdir(parents=True)
    (mono / "requirements").mkdir(parents=True)
    (mono / "services" / "api").mkdir(parents=True)
    (mono / "services" / "worker").mkdir(parents=True)

    (mono / "docs" / "requirements.txt").write_text("sphinx\npsycopg2-binary\n", encoding="utf-8")
    (mono / "requirements" / "dev.txt").write_text("pytest\n", encoding="utf-8")
    (mono / "services" / "api" / "uv.lock").write_text("", encoding="utf-8")
    (mono / "services" / "api" / "pyproject.toml").write_text(
        """
[project]
name = "api"
requires-python = ">=3.11"
dependencies = ["fastapi", "psycopg2-binary", "pytest", "ruff", "fakeredis"]
""",
        encoding="utf-8",
    )
    (mono / "services" / "worker" / "requirements.txt").write_text("celery\npytest\n", encoding="utf-8")
    (mono / "services" / "worker" / "worker.py").write_text("print('ok')\n", encoding="utf-8")

    indexer = RepoIndexer(mono)
    assert detector.detect(indexer) is True
    ctx = ProjectContext(repo_name="py_mono", repo_root=str(mono))
    detector.analyze(indexer, ctx)

    pkg_by_path = {p.path: p for p in ctx.monorepo_packages}
    assert sorted(pkg_by_path.keys()) == ["services/api", "services/worker"]

    api = pkg_by_path["services/api"]
    assert api.package_manager == "uv"
    assert api.runtime_version == "3.11"
    assert api.install_cmd == "uv sync --frozen"
    assert api.test_cmd == "uv run pytest"
    assert api.lint_cmd == "uv run ruff check ."
    assert api.framework == "FastAPI"
    assert api.cache_dependency_path == "services/api/uv.lock"

    worker = pkg_by_path["services/worker"]
    assert worker.package_manager == "pip"
    assert worker.install_cmd == "pip install -r requirements.txt"
    assert worker.cache_dependency_path == "services/worker/requirements.txt"

    # Mock fakeredis in services/api filtered; real celery in services/worker & psycopg2 in services/api kept & scoped
    svc_pairs = {(s.name, s.package_path) for s in ctx.services}
    assert svc_pairs == {("postgres", "services/api"), ("redis", "services/worker")}

    rep = ctx.get_language("python")
    assert rep is not None
    assert rep.is_workspace_root is None

    # 3. Active root Python + sub-package inheriting root uv.lock -> root has is_workspace_root=False
    hybrid_py = tmp_path / "hybrid_py"
    (hybrid_py / "services" / "ml").mkdir(parents=True)
    (hybrid_py / "uv.lock").write_text("", encoding="utf-8")
    (hybrid_py / ".python-version").write_text("3.12\n", encoding="utf-8")
    (hybrid_py / "pyproject.toml").write_text('[project]\nname = "root"\ndependencies = ["pytest"]\n', encoding="utf-8")
    (hybrid_py / "services" / "ml" / "pyproject.toml").write_text('[project]\nname = "ml"\n', encoding="utf-8")

    h_ctx = ProjectContext(repo_name="hybrid_py", repo_root=str(hybrid_py))
    detector.analyze(RepoIndexer(hybrid_py), h_ctx)
    assert h_ctx.get_language("python").working_dir == "."
    assert h_ctx.get_language("python").is_workspace_root is False
    assert len(h_ctx.monorepo_packages) == 1
    assert h_ctx.monorepo_packages[0].path == "services/ml"
    assert h_ctx.monorepo_packages[0].package_manager == "uv"
    assert h_ctx.monorepo_packages[0].cache_dependency_path == "uv.lock"


def test_matrix_signal_classifiers_tox_and_engines_node(tmp_path: Path):
    py_det = PythonDetector()
    node_det = NodeDetector()

    # 1. pyproject.toml classifiers extracted unconditionally even when .python-version exists (sorted numerically)
    cls_repo = tmp_path / "cls_repo"
    cls_repo.mkdir()
    (cls_repo / ".python-version").write_text("3.11\n", encoding="utf-8")
    (cls_repo / "pyproject.toml").write_text(
        """
[project]
name = "cls-app"
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12 :: Only",
]
""",
        encoding="utf-8",
    )
    cls_ctx = ProjectContext(repo_name="cls_repo", repo_root=str(cls_repo))
    py_det.analyze(RepoIndexer(cls_repo), cls_ctx)
    py_cls = cls_ctx.get_language("python")
    assert py_cls.runtime_version == "3.11"
    assert py_cls.matrix_versions == ["3.9", "3.10", "3.11", "3.12"]

    # 2. Single .python-version + single classifier must NOT trigger matrix_versions
    single_py = tmp_path / "single_py"
    single_py.mkdir()
    (single_py / ".python-version").write_text("3.12\n", encoding="utf-8")
    (single_py / "pyproject.toml").write_text(
        '[project]\nname = "single"\nclassifiers = ["Programming Language :: Python :: 3.12"]\n',
        encoding="utf-8",
    )
    single_ctx = ProjectContext(repo_name="single_py", repo_root=str(single_py))
    py_det.analyze(RepoIndexer(single_py), single_ctx)
    assert single_ctx.get_language("python").matrix_versions == []

    # 3. tox.ini envlist with brace expansion and interpolation placeholders ({posargs}, %(here)s)
    tox_repo = tmp_path / "tox_repo"
    tox_repo.mkdir()
    (tox_repo / "pyproject.toml").write_text('[project]\nname = "tox-app"\n', encoding="utf-8")
    (tox_repo / "tox.ini").write_text(
        """
[tox]
envlist = py{310,311,312}-django{42,50}, py3.13, lint

[testenv]
commands = pytest {posargs} %(toxinidir)s
""",
        encoding="utf-8",
    )
    tox_ctx = ProjectContext(repo_name="tox_repo", repo_root=str(tox_repo))
    py_det.analyze(RepoIndexer(tox_repo), tox_ctx)
    assert tox_ctx.get_language("python").matrix_versions == ["3.10", "3.11", "3.12", "3.13"]

    # 4. Node engines.node || multi-version vs single constraints
    node_matrix = tmp_path / "node_matrix"
    node_matrix.mkdir()
    (node_matrix / "package.json").write_text(
        '{"name": "nm", "engines": {"node": "18 || 20 || 22"}}',
        encoding="utf-8",
    )
    nm_ctx = ProjectContext(repo_name="node_matrix", repo_root=str(node_matrix))
    node_det.analyze(RepoIndexer(node_matrix), nm_ctx)
    assert nm_ctx.get_language("node").matrix_versions == ["18.x", "20.x", "22.x"]

    for idx, spec in enumerate([">=18", "^20.0.0", "20.x", ">=18 <21"]):
        single_node = tmp_path / f"single_node_{idx}"
        single_node.mkdir()
        (single_node / "package.json").write_text(
            f'{{"name": "sn", "engines": {{"node": "{spec}"}}}}',
            encoding="utf-8",
        )
        sn_ctx = ProjectContext(repo_name="sn", repo_root=str(single_node))
        node_det.analyze(RepoIndexer(single_node), sn_ctx)
        assert sn_ctx.get_language("node").matrix_versions == []


def test_rust_workspace_members_and_exclude(tmp_path: Path):
    detector = RustDetector()

    # 1. Virtual Cargo [workspace] (no [package]) with members/exclude and toolchain inheritance
    virt = tmp_path / "virt_rust"
    (virt / "crates" / "core").mkdir(parents=True)
    (virt / "crates" / "cli").mkdir(parents=True)
    (virt / "crates" / "ignored").mkdir(parents=True)
    (virt / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.79.0"\n', encoding="utf-8")
    (virt / "Cargo.lock").write_text("", encoding="utf-8")
    (virt / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/*"]\nexclude = ["crates/ignored"]\n',
        encoding="utf-8",
    )
    (virt / "crates" / "core" / "Cargo.toml").write_text(
        '[package]\nname = "core"\nversion = "0.1.0"\n[dependencies]\nactix-web = "4"\n',
        encoding="utf-8",
    )
    (virt / "crates" / "cli" / "rust-toolchain").write_text("1.80.0\n", encoding="utf-8")
    (virt / "crates" / "cli" / "Cargo.toml").write_text(
        '[package]\nname = "cli"\nversion = "0.1.0"\n[dependencies]\naxum = "0.7"\n',
        encoding="utf-8",
    )
    (virt / "crates" / "ignored" / "Cargo.toml").write_text(
        '[package]\nname = "ignored"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    v_indexer = RepoIndexer(virt)
    assert detector.detect(v_indexer) is True
    v_ctx = ProjectContext(repo_name="virt_rust", repo_root=str(virt))
    detector.analyze(v_indexer, v_ctx)

    assert v_ctx.is_monorepo is True
    root_rust = v_ctx.get_language("rust")
    assert root_rust is not None
    assert root_rust.working_dir == "."
    assert root_rust.is_workspace_root is True
    assert root_rust.runtime_version == "1.79.0"

    pkg_by_path = {p.path: p for p in v_ctx.monorepo_packages}
    assert sorted(pkg_by_path.keys()) == ["crates/cli", "crates/core"]
    assert pkg_by_path["crates/core"].framework == "Actix-Web"
    assert pkg_by_path["crates/core"].runtime_version == "1.79.0"
    assert pkg_by_path["crates/core"].cache_dependency_path == "Cargo.lock"
    assert pkg_by_path["crates/core"].install_cmd == "cargo fetch"
    assert pkg_by_path["crates/core"].build_cmd == "cargo build --release"
    assert pkg_by_path["crates/core"].test_cmd == "cargo test --verbose"
    assert pkg_by_path["crates/core"].lint_cmd == "cargo clippy -- -D warnings"
    assert pkg_by_path["crates/cli"].framework == "Axum"
    assert pkg_by_path["crates/cli"].runtime_version == "1.80.0"

    # 2. Root crate + workspace ([package] + [workspace]) -> active root crate has is_workspace_root=False
    hybrid = tmp_path / "hybrid_rust"
    (hybrid / "crates" / "sub").mkdir(parents=True)
    (hybrid / "Cargo.toml").write_text(
        '[package]\nname = "root-app"\nversion = "0.1.0"\n[workspace]\nmembers = ["crates/*"]\n',
        encoding="utf-8",
    )
    (hybrid / "crates" / "sub" / "Cargo.toml").write_text(
        '[package]\nname = "sub"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    h_ctx = ProjectContext(repo_name="hybrid_rust", repo_root=str(hybrid))
    detector.analyze(RepoIndexer(hybrid), h_ctx)
    assert h_ctx.is_monorepo is True
    assert h_ctx.get_language("rust").is_workspace_root is False
    assert sorted(p.path for p in h_ctx.monorepo_packages) == [".", "crates/sub"]

    # 3. Polyglot Rust sub-package without root Cargo.toml
    sub_only = tmp_path / "sub_rust"
    (sub_only / "crates" / "engine").mkdir(parents=True)
    (sub_only / "crates" / "engine" / "Cargo.toml").write_text(
        '[package]\nname = "engine"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    s_indexer = RepoIndexer(sub_only)
    assert detector.detect(s_indexer) is True
    s_ctx = ProjectContext(repo_name="sub_rust", repo_root=str(sub_only))
    detector.analyze(s_indexer, s_ctx)
    assert [p.path for p in s_ctx.monorepo_packages] == ["crates/engine"]
    assert s_ctx.get_language("rust").working_dir == "crates/engine"
    assert s_ctx.get_language("rust").is_workspace_root is None

    # 4. Single root Rust crate -> non-monorepo, is_workspace_root=False
    single = tmp_path / "single_rust"
    single.mkdir()
    (single / "Cargo.toml").write_text('[package]\nname = "solo"\nversion = "0.1.0"\n', encoding="utf-8")
    sg_ctx = ProjectContext(repo_name="single_rust", repo_root=str(single))
    detector.analyze(RepoIndexer(single), sg_ctx)
    assert sg_ctx.is_monorepo is False
    assert sg_ctx.monorepo_packages == []
    assert sg_ctx.get_language("rust").is_workspace_root is False


def test_go_work_workspace_modules(tmp_path: Path):
    from heurix.detectors.go_detector import GoDetector

    detector = GoDetector()

    # 1. Virtual go.work without root go.mod
    virt = tmp_path / "go_virt"
    (virt / "services" / "gateway").mkdir(parents=True)
    (virt / "services" / "billing").mkdir(parents=True)
    (virt / "services" / "unused").mkdir(parents=True)
    (virt / "go.work").write_text(
        "go 1.22\n\nuse (\n    ./services/gateway\n    ./services/billing\n)\n",
        encoding="utf-8",
    )
    (virt / "services" / "gateway" / "go.mod").write_text(
        "module example.com/gateway\n\ngo 1.21\n\nrequire github.com/gin-gonic/gin v1.9.1\n",
        encoding="utf-8",
    )
    (virt / "services" / "gateway" / "go.sum").write_text("", encoding="utf-8")
    (virt / "services" / "billing" / "go.mod").write_text(
        "module example.com/billing\n\ngo 1.22\n\nrequire github.com/labstack/echo/v4 v4.11.0\n",
        encoding="utf-8",
    )
    (virt / "services" / "unused" / "go.mod").write_text(
        "module example.com/unused\n\ngo 1.22\n",
        encoding="utf-8",
    )

    v_indexer = RepoIndexer(virt)
    assert detector.detect(v_indexer) is True
    v_ctx = ProjectContext(repo_name="go_virt", repo_root=str(virt))
    detector.analyze(v_indexer, v_ctx)

    assert v_ctx.is_monorepo is True
    root_go = v_ctx.get_language("go")
    assert root_go is not None
    assert root_go.working_dir == "."
    assert root_go.is_workspace_root is True

    pkg_by_path = {p.path: p for p in v_ctx.monorepo_packages}
    assert sorted(pkg_by_path.keys()) == ["services/billing", "services/gateway"]

    gw = pkg_by_path["services/gateway"]
    assert gw.package_manager == "gomod"
    assert gw.runtime_version == "1.21"
    assert gw.framework == "Gin"
    assert gw.cache_dependency_path == "services/gateway/go.sum"
    assert gw.install_cmd == "go mod download"
    assert gw.build_cmd == "go build -v ./..."
    assert gw.test_cmd == "go test -v -race -cover ./..."
    assert gw.lint_cmd == "golangci-lint run"

    bill = pkg_by_path["services/billing"]
    assert bill.runtime_version == "1.22"
    assert bill.framework == "Echo"
    assert bill.cache_dependency_path is None

    # 2. go.work with active root go.mod (`use .`) -> root LanguageContext is_workspace_root=False
    active = tmp_path / "go_active"
    (active / "services" / "api").mkdir(parents=True)
    (active / "go.work").write_text("go 1.22\nuse (\n  .\n  ./services/api\n)\n", encoding="utf-8")
    (active / "go.mod").write_text("module example.com/root\n\ngo 1.22\n", encoding="utf-8")
    (active / "services" / "api" / "go.mod").write_text("module example.com/api\n\ngo 1.22\n", encoding="utf-8")

    a_ctx = ProjectContext(repo_name="go_active", repo_root=str(active))
    detector.analyze(RepoIndexer(active), a_ctx)
    assert a_ctx.is_monorepo is True
    assert a_ctx.get_language("go").working_dir == "."
    assert a_ctx.get_language("go").is_workspace_root is False
    assert [p.path for p in a_ctx.monorepo_packages] == ["services/api"]

    # 3. Polyglot sub-package without go.work or root go.mod
    sub = tmp_path / "go_sub"
    (sub / "services" / "auth").mkdir(parents=True)
    (sub / "services" / "auth" / "go.mod").write_text("module example.com/auth\n\ngo 1.23\n", encoding="utf-8")
    (sub / "services" / "auth" / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")

    s_indexer = RepoIndexer(sub)
    assert detector.detect(s_indexer) is True
    s_ctx = ProjectContext(repo_name="go_sub", repo_root=str(sub))
    detector.analyze(s_indexer, s_ctx)
    assert [p.path for p in s_ctx.monorepo_packages] == ["services/auth"]
    assert s_ctx.get_language("go").working_dir == "services/auth"
    assert s_ctx.get_language("go").is_workspace_root is None


def test_cpp_subpackage_polyglot_detection(tmp_path: Path):
    from heurix.detectors.cpp_detector import CppDetector

    detector = CppDetector()

    # 1. Polyglot C++ sub-package without root C++ manifest
    sub = tmp_path / "cpp_sub"
    (sub / "services" / "engine").mkdir(parents=True)
    (sub / "services" / "engine" / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\nproject(engine)\nset(CMAKE_CXX_STANDARD 20)\n",
        encoding="utf-8",
    )
    (sub / "services" / "engine" / ".clang-tidy").write_text("Checks: '*'\n", encoding="utf-8")
    (sub / "services" / "engine" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")

    s_indexer = RepoIndexer(sub)
    assert detector.detect(s_indexer) is True
    s_ctx = ProjectContext(repo_name="cpp_sub", repo_root=str(sub))
    detector.analyze(s_indexer, s_ctx)

    assert len(s_ctx.monorepo_packages) == 1
    eng = s_ctx.monorepo_packages[0]
    assert eng.path == "services/engine"
    assert eng.language == "cpp"
    assert eng.package_manager == "cmake"
    assert eng.runtime_version == "c++20"
    assert eng.version_source == "CMakeLists.txt"
    assert eng.lint_cmd == "clang-tidy -p build"
    assert s_ctx.get_language("cpp").working_dir == "services/engine"
    assert s_ctx.get_language("cpp").is_workspace_root is None

    # 2. Root CMake project with internal add_subdirectory(src) must NOT duplicate into monorepo_packages
    root_cmake = tmp_path / "cpp_root"
    (root_cmake / "src").mkdir(parents=True)
    (root_cmake / "CMakeLists.txt").write_text(
        "project(app)\nset(CMAKE_CXX_STANDARD 17)\nadd_subdirectory(src)\n",
        encoding="utf-8",
    )
    (root_cmake / "src" / "CMakeLists.txt").write_text("add_library(core lib.cpp)\n", encoding="utf-8")

    r_ctx = ProjectContext(repo_name="cpp_root", repo_root=str(root_cmake))
    detector.analyze(RepoIndexer(root_cmake), r_ctx)
    assert r_ctx.is_monorepo is False
    assert r_ctx.monorepo_packages == []
    assert r_ctx.get_language("cpp").working_dir == "."
    assert r_ctx.get_language("cpp").is_workspace_root is False

    # 3. Root CMake + independent sub-packages (preferred group + conan standalone)
    mono_cmake = tmp_path / "cpp_mono"
    (mono_cmake / "services" / "engine").mkdir(parents=True)
    (mono_cmake / "standalone").mkdir(parents=True)
    (mono_cmake / "CMakeLists.txt").write_text("project(mono)\nset(CMAKE_CXX_STANDARD 17)\n", encoding="utf-8")
    (mono_cmake / "services" / "engine" / "CMakeLists.txt").write_text(
        "project(engine)\nset(CMAKE_CXX_STANDARD 20)\n",
        encoding="utf-8",
    )
    (mono_cmake / "standalone" / "conanfile.txt").write_text("[requires]\nfmt/10.0.0\n", encoding="utf-8")
    (mono_cmake / "standalone" / "CMakeLists.txt").write_text(
        "project(standalone)\nset(CMAKE_CXX_STANDARD 23)\n",
        encoding="utf-8",
    )

    m_ctx = ProjectContext(repo_name="cpp_mono", repo_root=str(mono_cmake))
    detector.analyze(RepoIndexer(mono_cmake), m_ctx)
    assert m_ctx.get_language("cpp").working_dir == "."
    assert m_ctx.get_language("cpp").is_workspace_root is False
    m_pkgs = {p.path: p for p in m_ctx.monorepo_packages}
    assert sorted(m_pkgs.keys()) == ["services/engine", "standalone"]
    assert m_pkgs["services/engine"].runtime_version == "c++20"
    assert m_pkgs["standalone"].package_manager == "conan"
    assert m_pkgs["standalone"].runtime_version == "c++23"


def test_polyglot_monorepo_nested_gitignore_end_to_end(tmp_path: Path):
    from heurix.detectors import analyze_repository

    # 1. Polyglot monorepo: Node in apps/web + Python in services/api + nested .gitignore hiding local_build/
    mono = tmp_path / "poly_mono"
    (mono / "apps" / "web" / "local_build").mkdir(parents=True)
    (mono / "services" / "api").mkdir(parents=True)
    (mono / "docs").mkdir(parents=True)

    (mono / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (mono / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (mono / "apps" / "web" / ".gitignore").write_text("local_build/\n", encoding="utf-8")
    (mono / "apps" / "web" / "package.json").write_text(
        '{"name": "web", "scripts": {"test": "vitest run", "build": "next build"}, "dependencies": {"next": "^14.0.0"}}',
        encoding="utf-8",
    )
    # Must be hidden by apps/web/.gitignore and never indexed or picked up as a package
    (mono / "apps" / "web" / "local_build" / "package.json").write_text('{"name": "ignored"}', encoding="utf-8")
    (mono / "apps" / "web" / "local_build" / "pyproject.toml").write_text('[project]\nname = "ignored"\n', encoding="utf-8")

    (mono / "services" / "api" / "uv.lock").write_text("", encoding="utf-8")
    (mono / "services" / "api" / "pyproject.toml").write_text(
        """
[project]
name = "api"
requires-python = ">=3.11"
dependencies = ["fastapi", "psycopg2-binary", "pytest"]
""",
        encoding="utf-8",
    )
    (mono / "docs" / "requirements.txt").write_text("sphinx\n", encoding="utf-8")

    ctx = analyze_repository(mono)
    assert ctx.is_monorepo is True
    assert [(p.path, p.language) for p in ctx.monorepo_packages] == [
        ("apps/web", "node"),
        ("services/api", "python"),
    ]
    pkg_map = {(p.path, p.language): p for p in ctx.monorepo_packages}
    assert pkg_map[("apps/web", "node")].cache_dependency_path == "pnpm-lock.yaml"
    assert pkg_map[("services/api", "python")].cache_dependency_path == "services/api/uv.lock"
    assert pkg_map[("services/api", "python")].framework == "FastAPI"
    assert [(s.name, s.package_path) for s in ctx.services] == [("postgres", "services/api")]

    # 2. Hybrid root Python + 1 Node sub-package -> is_monorepo reconciled to True
    hybrid = tmp_path / "hybrid_mono"
    (hybrid / "frontend").mkdir(parents=True)
    (hybrid / "pyproject.toml").write_text('[project]\nname = "api"\n', encoding="utf-8")
    (hybrid / "frontend" / "package.json").write_text('{"name": "frontend"}', encoding="utf-8")

    h_ctx = analyze_repository(hybrid)
    assert h_ctx.is_monorepo is True
    assert [(p.path, p.language) for p in h_ctx.monorepo_packages] == [("frontend", "node")]


def test_toml_matrix_and_scalar_override_precedence(tmp_path: Path):
    from heurix.detectors import analyze_repository

    # 1. [matrix] table populates matrix_os and *-version aliases across LanguageContext and MonorepoPackage
    repo1 = tmp_path / "matrix_repo"
    (repo1 / "services" / "api").mkdir(parents=True)
    (repo1 / "apps" / "web").mkdir(parents=True)
    (repo1 / "services" / "api" / "pyproject.toml").write_text('[project]\nname = "api"\n', encoding="utf-8")
    (repo1 / "apps" / "web" / "package.json").write_text('{"name": "web"}', encoding="utf-8")
    (repo1 / ".heurix.toml").write_text(
        """
[matrix]
os = ["ubuntu-latest", "macos-latest"]
python-version = ["3.11", "3.12", "3.13"]
node = ["20.x", "22.x"]
""",
        encoding="utf-8",
    )

    ctx1 = analyze_repository(repo1)
    assert ctx1.matrix_os == ["ubuntu-latest", "macos-latest"]
    py_lang = ctx1.get_language("python")
    assert py_lang.matrix_versions == ["3.11", "3.12", "3.13"]
    assert py_lang.runtime_version == "3.13"
    assert py_lang.version_source == ".heurix.toml"

    py_pkg = next(p for p in ctx1.monorepo_packages if p.language == "python")
    assert py_pkg.matrix_versions == ["3.11", "3.12", "3.13"]
    assert py_pkg.runtime_version == "3.13"
    assert py_pkg.version_source == ".heurix.toml"

    node_pkg = next(p for p in ctx1.monorepo_packages if p.language == "node")
    assert node_pkg.matrix_versions == ["20.x", "22.x"]
    assert node_pkg.runtime_version == "22.x"
    assert node_pkg.version_source == ".heurix.toml"

    # 2. Single-entry [matrix] lists resolve to scalar runner/runtime_version without matrix expansion
    repo2 = tmp_path / "single_matrix_entry"
    repo2.mkdir()
    (repo2 / "pyproject.toml").write_text('[project]\nname = "solo"\n', encoding="utf-8")
    (repo2 / ".heurix.toml").write_text(
        """
[matrix]
os = ["ubuntu-22.04"]
python = ["3.11"]
""",
        encoding="utf-8",
    )
    ctx2 = analyze_repository(repo2)
    assert ctx2.matrix_os == []
    assert ctx2.runner == "ubuntu-22.04"
    assert ctx2.get_language("python").runtime_version == "3.11"
    assert ctx2.get_language("python").matrix_versions == []

    # 3. [overrides] list values map to matrix_versions without str(list) coercion
    repo3 = tmp_path / "list_override"
    repo3.mkdir()
    (repo3 / "pyproject.toml").write_text('[project]\nname = "app"\n', encoding="utf-8")
    (repo3 / ".heurix.toml").write_text(
        """
[overrides]
python = ["3.11", "3.12"]
""",
        encoding="utf-8",
    )
    ctx3 = analyze_repository(repo3)
    py3 = ctx3.get_language("python")
    assert py3.matrix_versions == ["3.11", "3.12"]
    assert py3.runtime_version == "3.12"
    assert "[" not in py3.runtime_version
    assert py3.version_source == ".heurix.toml"

    # 4. Scalar [overrides] collapses pyproject.toml classifiers AND [matrix] across all matching contexts/packages
    repo4 = tmp_path / "scalar_collapse"
    (repo4 / "services" / "a").mkdir(parents=True)
    (repo4 / "services" / "b").mkdir(parents=True)
    for sub in ("a", "b"):
        (repo4 / "services" / sub / "pyproject.toml").write_text(
            """
[project]
name = "svc"
classifiers = [
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
""",
            encoding="utf-8",
        )
    (repo4 / ".heurix.toml").write_text(
        """
[matrix]
python = ["3.10", "3.11", "3.12"]

[overrides]
python = "3.11"
""",
        encoding="utf-8",
    )
    ctx4 = analyze_repository(repo4)
    for lang in ctx4.get_languages("python"):
        assert lang.runtime_version == "3.11"
        assert lang.version_source == ".heurix.toml"
        assert lang.matrix_versions == []
    for pkg in ctx4.monorepo_packages:
        assert pkg.runtime_version == "3.11"
        assert pkg.version_source == ".heurix.toml"
        assert pkg.matrix_versions == []

    # 5. Malformed .heurix.toml degrades gracefully with explain_log warning
    repo5 = tmp_path / "bad_toml"
    repo5.mkdir()
    (repo5 / "pyproject.toml").write_text('[project]\nname = "app"\n', encoding="utf-8")
    (repo5 / ".heurix.toml").write_text("[overrides\npython = broken", encoding="utf-8")
    ctx5 = analyze_repository(repo5)
    assert any("Warning: Failed to parse .heurix.toml" in msg for msg in ctx5.explain_log)


def test_e2e_and_unit_runner_detection(tmp_path: Path):
    from heurix.detectors import analyze_repository

    # (a) Root Node repo with vitest + @playwright/test + scripts["test:e2e"]
    node_root = tmp_path / "node_root"
    node_root.mkdir()
    (node_root / "package-lock.json").write_text("{}", encoding="utf-8")
    (node_root / "package.json").write_text(
        """{
        "name": "node-e2e-app",
        "scripts": {
            "test": "vitest run",
            "test:e2e": "playwright test"
        },
        "devDependencies": {
            "vitest": "^2.0.0",
            "@playwright/test": "^1.48.0"
        }
    }""",
        encoding="utf-8",
    )
    node_ctx = analyze_repository(node_root)
    assert node_ctx.split_e2e_jobs is None
    node_lang = node_ctx.get_language("node")
    assert node_lang is not None
    assert node_lang.test_cmd == "npm test"
    assert node_lang.unit_test_runner == "vitest"
    assert node_lang.e2e_test_runner == "playwright"
    assert node_lang.e2e_cmd == "npm run test:e2e"

    # (b) pnpm monorepo package with jest + cypress.config.ts (fallback exec runner)
    mono = tmp_path / "pnpm_mono_e2e"
    (mono / "apps" / "web").mkdir(parents=True)
    (mono / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (mono / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (mono / "package.json").write_text('{"name": "root", "private": true}', encoding="utf-8")
    (mono / "apps" / "web" / "package.json").write_text(
        """{
        "name": "@acme/web",
        "scripts": {
            "test": "jest --ci"
        },
        "devDependencies": {
            "jest": "^29.7.0"
        }
    }""",
        encoding="utf-8",
    )
    (mono / "apps" / "web" / "cypress.config.ts").write_text(
        "export default { e2e: {} };\n", encoding="utf-8"
    )
    mono_ctx = analyze_repository(mono)
    web_pkg = next(p for p in mono_ctx.monorepo_packages if p.path == "apps/web")
    assert web_pkg.test_cmd == "pnpm test"
    assert web_pkg.unit_test_runner == "jest"
    assert web_pkg.e2e_test_runner == "cypress"
    assert web_pkg.e2e_cmd == "pnpm exec cypress run"

    # (c) Python uv repo with pytest in pyproject.toml + pytest-playwright in requirements-dev.txt + tests/e2e/test_flow.py
    py_repo = tmp_path / "py_uv_e2e"
    (py_repo / "tests" / "e2e").mkdir(parents=True)
    (py_repo / "uv.lock").write_text("", encoding="utf-8")
    (py_repo / "pyproject.toml").write_text(
        """
[project]
name = "py-e2e"
dependencies = ["fastapi", "pytest"]
""",
        encoding="utf-8",
    )
    (py_repo / "requirements-dev.txt").write_text("pytest-playwright>=0.5.0\n", encoding="utf-8")
    (py_repo / "tests" / "e2e" / "test_flow.py").write_text(
        "def test_smoke(): pass\n", encoding="utf-8"
    )
    py_ctx = analyze_repository(py_repo)
    py_lang = py_ctx.get_language("python")
    assert py_lang is not None
    assert py_lang.test_cmd == "uv run pytest"
    assert py_lang.unit_test_runner == "pytest"
    assert py_lang.e2e_test_runner == "playwright"
    assert py_lang.e2e_cmd == "uv run pytest tests/e2e"

    # (d) Additional edge cases: Python playwright.config.py fallback (-k e2e), e2e/ dir, Node mocha + E2E-only
    py_cfg = tmp_path / "py_cfg_e2e"
    py_cfg.mkdir()
    (py_cfg / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (py_cfg / "playwright.config.py").write_text("# playwright\n", encoding="utf-8")
    py_cfg_ctx = analyze_repository(py_cfg)
    py_cfg_lang = py_cfg_ctx.get_language("python")
    assert py_cfg_lang is not None
    assert py_cfg_lang.test_cmd == "pytest"
    assert py_cfg_lang.unit_test_runner == "pytest"
    assert py_cfg_lang.e2e_test_runner == "playwright"
    assert py_cfg_lang.e2e_cmd == "pytest -k e2e"

    py_e2e_dir = tmp_path / "py_e2e_dir"
    (py_e2e_dir / "e2e").mkdir(parents=True)
    (py_e2e_dir / "pyproject.toml").write_text('[project]\nname="app"\ndependencies=["pytest"]\n', encoding="utf-8")
    (py_e2e_dir / "e2e" / "test_browser.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    py_dir_ctx = analyze_repository(py_e2e_dir)
    py_dir_lang = py_dir_ctx.get_language("python")
    assert py_dir_lang is not None
    assert py_dir_lang.e2e_test_runner == "playwright"
    assert py_dir_lang.e2e_cmd == "pytest e2e"

    node_e2e_only = tmp_path / "node_e2e_only"
    node_e2e_only.mkdir()
    (node_e2e_only / "package.json").write_text(
        '{"name": "e2e-only", "scripts": {"test": "playwright test"}, "devDependencies": {"@playwright/test": "^1.48.0"}}',
        encoding="utf-8",
    )
    e2e_only_ctx = analyze_repository(node_e2e_only)
    e2e_only_lang = e2e_only_ctx.get_language("node")
    assert e2e_only_lang is not None
    assert e2e_only_lang.unit_test_runner is None
    assert e2e_only_lang.e2e_test_runner == "playwright"
    assert e2e_only_lang.e2e_cmd == "npx playwright test"

    node_mocha = tmp_path / "node_mocha"
    node_mocha.mkdir()
    (node_mocha / "package.json").write_text(
        '{"name": "mocha-app", "scripts": {"test": "mocha"}, "devDependencies": {"mocha": "^10.0.0"}}',
        encoding="utf-8",
    )
    mocha_ctx = analyze_repository(node_mocha)
    mocha_lang = mocha_ctx.get_language("node")
    assert mocha_lang is not None
    assert mocha_lang.unit_test_runner == "mocha"
    assert mocha_lang.e2e_test_runner is None
    assert mocha_lang.e2e_cmd is None

    # JSON round-trip preserves new IR fields
    rehydrated = ProjectContext.model_validate_json(node_ctx.model_dump_json())
    rehydrated_node = rehydrated.get_language("node")
    assert rehydrated_node is not None
    assert rehydrated_node.unit_test_runner == "vitest"
    assert rehydrated_node.e2e_test_runner == "playwright"
    assert rehydrated_node.e2e_cmd == "npm run test:e2e"

