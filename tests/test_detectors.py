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


