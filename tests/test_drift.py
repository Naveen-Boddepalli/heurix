"""
Tests for Drift Detection.
"""

from __future__ import annotations

from pathlib import Path
from heurix.core.context import LanguageContext, ProjectContext, ServiceRequirement
from heurix.core.drift import DriftDetector, inspect_workflow_ast


def test_drift_detector_flags_missing_service(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
        services=[
            ServiceRequirement(
                name="redis",
                image="redis:7-alpine",
                ports=[6379],
                source_file="pyproject.toml",
            )
        ],
    )

    synthesized = {".github/workflows/ci.yml": "dummy"}
    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, synthesized)

    assert len(findings) > 0
    assert any("redis" in f.issue.lower() for f in findings)


def test_ast_drift_services_discovered_across_auxiliary_jobs(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
  integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
      redis:
        image: redis:7-alpine
    steps:
      - uses: actions/checkout@v4
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
        services=[
            ServiceRequirement(name="postgres", image="postgres:16-alpine", ports=[5432], source_file="pyproject.toml"),
            ServiceRequirement(name="redis", image="redis:7-alpine", ports=[6379], source_file="pyproject.toml"),
        ],
    )

    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})

    assert findings == []


def test_ast_drift_services_rejects_comment_false_positives(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
# services:
#   redis:
#     image: redis:7-alpine
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install redis-tools note
        run: echo "remember redis and install redis-tools"
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
        services=[
            ServiceRequirement(name="postgres", image="postgres:16-alpine", ports=[5432], source_file="pyproject.toml"),
            ServiceRequirement(name="redis", image="redis:7-alpine", ports=[6379], source_file="pyproject.toml"),
        ],
    )

    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})

    assert len(findings) == 1
    assert "redis" in findings[0].issue.lower()
    assert "postgres" not in findings[0].issue.lower()


def test_ast_drift_services_flags_missing_when_other_jobs_exist(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
  e2e:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
    steps:
      - uses: actions/checkout@v4
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
        services=[
            ServiceRequirement(name="postgres", image="postgres:16-alpine", ports=[5432], source_file="docker-compose.yml"),
            ServiceRequirement(name="mongodb", image="mongo:6", ports=[27017], source_file="package.json"),
        ],
    )

    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})

    assert len(findings) == 1
    assert "mongodb" in findings[0].issue.lower()


def test_ast_runtime_version_setup_actions(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    ci_path = workflow_dir / "ci.yml"
    ci_path.write_text(
        """
name: CI
jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@82c7e631bb3cdc910f68e0081d67478d79c6982d
        with:
          python-version: '3.12'
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
  services-go:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'
  rust-crate:
    runs-on: ubuntu-latest
    steps:
      - uses: dtolnay/rust-toolchain@stable
        with:
          toolchain: '1.78'
""",
        encoding="utf-8",
    )

    matching_context = ProjectContext(
        repo_name="polyglot",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            ),
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
            ),
            LanguageContext(
                language="go",
                runtime_version="1.22",
                version_source="go.mod",
                package_manager="gomod",
                install_cmd="go mod download",
            ),
            LanguageContext(
                language="rust",
                runtime_version="1.78",
                version_source="rust-toolchain.toml",
                package_manager="cargo",
                install_cmd="cargo fetch",
            ),
        ],
    )

    detector = DriftDetector(tmp_path)
    assert detector.check_drift(matching_context, {".github/workflows/ci.yml": "dummy"}) == []

    mismatch_context = ProjectContext(
        repo_name="polyglot",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.13",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            ),
            LanguageContext(
                language="node",
                runtime_version="22.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
            ),
            LanguageContext(
                language="go",
                runtime_version="1.23",
                version_source="go.mod",
                package_manager="gomod",
                install_cmd="go mod download",
            ),
            LanguageContext(
                language="rust",
                runtime_version="1.80",
                version_source="rust-toolchain.toml",
                package_manager="cargo",
                install_cmd="cargo fetch",
            ),
        ],
    )

    findings = detector.check_drift(mismatch_context, {".github/workflows/ci.yml": "dummy"})
    issues = [f.issue for f in findings]
    assert len(findings) == 4
    assert any("python 3.13" in issue for issue in issues)
    assert any("node 22.x" in issue for issue in issues)
    assert any("go 1.23" in issue for issue in issues)
    assert any("rust 1.80" in issue for issue in issues)


def test_ast_runtime_version_rejects_comments_log_strings_and_tool_tags(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
# Target versions: python 3.12, node 20.x, go 1.22
env:
  DECOY_PYTHON: "3.12"
  DECOY_NODE: "20.x"
  DECOY_GO: "1.22"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: some/tool@v3.12.0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - uses: actions/setup-node@v4
        with:
          node-version: '18.x'
      - uses: actions/setup-go@v5
        with:
          go-version: '1.21'
      - name: Check python 3.12 node 20.x go 1.22 migration
        run: echo "upgrading from 3.11 to 3.12, 20.x, 1.22"
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            ),
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
            ),
            LanguageContext(
                language="go",
                runtime_version="1.22",
                version_source="go.mod",
                package_manager="gomod",
                install_cmd="go mod download",
            ),
        ],
    )

    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})
    issues = [f.issue for f in findings]

    assert len(findings) == 3
    assert any("python 3.12" in issue for issue in issues)
    assert any("node 20.x" in issue for issue in issues)
    assert any("go 1.22" in issue for issue in issues)


def test_matrix_strategy_version_resolution(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
jobs:
  python-matrix:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']
        include:
          - python-version: '3.13'
            os: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
  node-matrix:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: ['18.x', '20.x']
    steps:
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
  go-custom-matrix:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        go_rel: ['1.22']
    steps:
      - uses: actions/setup-go@v5
        with:
          go-version: ${{ matrix.go_rel }}
""",
        encoding="utf-8",
    )

    detector = DriftDetector(tmp_path)
    matched_ctx = ProjectContext(
        repo_name="matrix-app",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.13",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            ),
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
            ),
            LanguageContext(
                language="go",
                runtime_version="1.22",
                version_source="go.mod",
                package_manager="gomod",
                install_cmd="go mod download",
            ),
        ],
    )
    assert detector.check_drift(matched_ctx, {".github/workflows/ci.yml": "dummy"}) == []

    missing_ctx = ProjectContext(
        repo_name="matrix-app",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.10",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
    )
    findings = detector.check_drift(missing_ctx, {".github/workflows/ci.yml": "dummy"})
    assert len(findings) == 1
    assert "Runtime version mismatch" in findings[0].issue
    assert "python 3.10" in findings[0].issue


def test_matrix_does_not_leak_across_jobs(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
jobs:
  decoy:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.12']
    steps:
      - uses: actions/checkout@v4
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
    )

    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})
    assert len(findings) == 1
    assert "Runtime version mismatch" in findings[0].issue


def test_version_float_normalization(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    ci_file = workflow_dir / "ci.yml"

    # Quoted '3.10' matches '3.10', and unquoted float 3.12 matches '3.12'
    ci_file.write_text(
        """
name: CI
jobs:
  py310:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: " '3.10' "
  py312:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: 3.12
""",
        encoding="utf-8",
    )

    detector = DriftDetector(tmp_path)
    ok_ctx = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.10",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
    )
    assert detector.check_drift(ok_ctx, {".github/workflows/ci.yml": "dummy"}) == []

    # '3.1' must NOT match '3.10' via float equality
    ci_file.write_text(
        """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: 3.1
""",
        encoding="utf-8",
    )
    findings = detector.check_drift(ok_ctx, {".github/workflows/ci.yml": "dummy"})
    assert len(findings) == 1
    assert "python 3.10" in findings[0].issue


def test_ast_package_manager_detection(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    ci_file = workflow_dir / "ci.yml"
    detector = DriftDetector(tmp_path)

    # 1. Valid setup actions (including SHA-pinned) satisfy uv, pnpm, poetry
    ci_file.write_text(
        """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: astral-sh/setup-uv@a1b2c3d4e5f60718293a
        with:
          python-version: '3.12'
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
          cache: pnpm
""",
        encoding="utf-8",
    )
    ctx_uv_pnpm = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="uv",
                install_cmd="uv sync --frozen",
            ),
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="pnpm",
                install_cmd="pnpm i --frozen-lockfile",
            ),
        ],
    )
    assert detector.check_drift(ctx_uv_pnpm, {".github/workflows/ci.yml": "dummy"}) == []

    # 2. Valid CLI command prefixes in run steps satisfy package managers without setup actions
    ci_file.write_text(
        """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: |
          # Install dependencies
          uv sync --frozen
          uv run pytest
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
      - run: pnpm i --frozen-lockfile && pnpm test
""",
        encoding="utf-8",
    )
    assert detector.check_drift(ctx_uv_pnpm, {".github/workflows/ci.yml": "dummy"}) == []

    # 3. Decoy comments, step names, echo logs, and substring packages must NOT satisfy uv/pnpm/poetry
    ci_file.write_text(
        """
name: CI
# Uses astral-sh/setup-uv, pnpm/action-setup, snok/install-poetry
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Consider switching to astral-sh/setup-uv and poetry
        run: |
          # uv sync --frozen
          echo "not using uv or pnpm or poetry yet"
          pip install uv-tools
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
      - name: Consider pnpm migration
        run: npm ci
""",
        encoding="utf-8",
    )
    findings = detector.check_drift(ctx_uv_pnpm, {".github/workflows/ci.yml": "dummy"})
    issues = [f.issue.lower() for f in findings]
    assert len(findings) == 2
    assert any("uv" in issue for issue in issues)
    assert any("pnpm" in issue for issue in issues)

    # 4. Poetry verification: snok/install-poetry and decoy rejection
    ctx_poetry = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="poetry",
                install_cmd="poetry install --no-interaction",
            )
        ],
    )
    poetry_findings = detector.check_drift(ctx_poetry, {".github/workflows/ci.yml": "dummy"})
    assert len(poetry_findings) == 1
    assert "poetry" in poetry_findings[0].issue.lower()

    ci_file.write_text(
        """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: snok/install-poetry@v1
      - run: poetry install --no-interaction
""",
        encoding="utf-8",
    )
    assert detector.check_drift(ctx_poetry, {".github/workflows/ci.yml": "dummy"}) == []


def test_ast_env_and_unpinned_and_inspect_helper(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    ci_file = workflow_dir / "ci.yml"
    ci_file.write_text(
        """
name: CI
env:
  PY_VER: "3.12"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PY_VER }}
  unpinned-runner:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
    )

    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})
    assert len(findings) == 1
    assert "unpinned" in findings[0].issue.lower()
    assert "unpinned-runner" in findings[0].issue

    # Direct inspect_workflow_ast edge cases: non-dict, jobs: null, valid structure
    empty_info = inspect_workflow_ast({"jobs": None})
    assert empty_info.discovered_services == set()
    assert empty_info.setup_actions == set()
    assert inspect_workflow_ast(None).discovered_services == set()


def test_multijob_drift_monorepo_working_dir_and_packages(tmp_path: Path):
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.drift import WorkflowASTInfo
    from heurix.synthesizers.github_actions import GitHubActionsSynthesizer

    # Backward-compatible 6-arg positional WorkflowASTInfo + independent defaults
    a = WorkflowASTInfo(set(), {"python": set()}, set(), set(), [], {})
    b = WorkflowASTInfo(set(), {"python": set()}, set(), set(), [], {})
    a.working_dirs.add("apps/web")
    assert b.working_dirs == set()

    context = ProjectContext(
        repo_name="mono-drift",
        repo_root=str(tmp_path),
        is_monorepo=True,
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source="package.json",
                package_manager="pnpm",
                install_cmd="pnpm install",
                is_workspace_root=True,
            ),
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="uv",
                install_cmd="uv sync --frozen",
                working_dir="services/api",
                is_workspace_root=None,
            ),
        ],
        monorepo_packages=[
            MonorepoPackage(
                name="apps/web",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                runtime_version="20.x",
                version_source=".nvmrc",
                install_cmd="pnpm i --frozen-lockfile",
                test_cmd="pnpm test",
                cache_dependency_path="pnpm-lock.yaml",
            ),
            MonorepoPackage(
                name="services/api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                version_source=".python-version",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
                cache_dependency_path="services/api/uv.lock",
            ),
            MonorepoPackage(
                name="crates/core",
                path="crates/core",
                language="rust",
                package_manager="cargo",
                runtime_version="stable",
                version_source="default",
                install_cmd="cargo fetch",
                test_cmd="cargo test",
            ),
            MonorepoPackage(
                name="services/worker",
                path="services/worker",
                language="go",
                package_manager="gomod",
                runtime_version="1.22",
                version_source="go.mod",
                install_cmd="go mod download",
                test_cmd="go test ./...",
            ),
        ],
        services=[
            ServiceRequirement(
                name="postgres",
                image="postgres:16-alpine",
                ports=[5432],
                source_file="services/api/pyproject.toml",
                package_path="services/api",
            )
        ],
    )

    synthesized = GitHubActionsSynthesizer().synthesize(context)
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    ci_file = wf_dir / "ci.yml"
    ci_file.write_text(synthesized[".github/workflows/ci.yml"], encoding="utf-8")

    detector = DriftDetector(tmp_path)
    assert detector.check_drift(context, synthesized) == []

    ast_info = inspect_workflow_ast(YAML(typ="safe").load(ci_file.read_text(encoding="utf-8")))
    assert {"apps/web", "services/api", "crates/core", "services/worker"}.issubset(ast_info.working_dirs)
    assert ast_info.job_working_dirs["test-apps-web"] == "apps/web"
    assert ast_info.job_working_dirs["test-services-api"] == "services/api"
    assert "3.12" in ast_info.job_runtime_versions["test-services-api"]["python"]
    assert "uv" in ast_info.job_package_managers["test-services-api"]
    assert "pnpm" in ast_info.job_package_managers["test-apps-web"]
    assert ast_info.runs_on_oses == {"ubuntu-latest"}

    # Step-level working-directory normalization (./apps/web/ -> apps/web)
    step_wd_info = inspect_workflow_ast(
        {
            "jobs": {
                "step-job": {
                    "runs-on": "ubuntu-latest",
                    "steps": [
                        {"run": "pnpm test", "working-directory": "./apps/web/"},
                    ],
                }
            }
        }
    )
    assert "apps/web" in step_wd_info.working_dirs
    assert step_wd_info.job_working_dirs["step-job"] == "apps/web"

    # 1. Missing working-directory on services/api must be flagged
    ci_file.write_text(
        """name: CI
jobs:
  test-apps-web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
  test-services-api:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
    steps:
      - uses: astral-sh/setup-uv@v5
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
  test-crates-core:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: crates/core
    steps:
      - uses: dtolnay/rust-toolchain@stable
        with:
          toolchain: stable
  test-services-worker:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/worker
    steps:
      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'
""",
        encoding="utf-8",
    )
    missing_wd_findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})
    assert any("services/api" in f.issue and "working-directory" in f.issue for f in missing_wd_findings)

    # 2. Per-job isolation: test-services-api has python 3.10 + pip while unrelated job has 3.12 + uv
    ci_file.write_text(
        """name: CI
jobs:
  test-apps-web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
  test-services-api:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/api
    services:
      postgres:
        image: postgres:16-alpine
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
  decoy-other-python:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: tools/helper
    steps:
      - uses: astral-sh/setup-uv@v5
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
  test-crates-core:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: crates/core
    steps:
      - uses: dtolnay/rust-toolchain@stable
        with:
          toolchain: stable
  test-services-worker:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/worker
    steps:
      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'
""",
        encoding="utf-8",
    )
    isolated_findings = detector.check_drift(context, {".github/workflows/ci.yml": "dummy"})
    assert any("3.12" in f.issue and "services/api" in f.issue for f in isolated_findings)
    assert any("uv" in f.issue.lower() and "services/api" in f.issue for f in isolated_findings)


def test_matrix_drift_versions_and_os_roundtrip(tmp_path: Path):
    from heurix.core.context import MonorepoPackage
    from heurix.synthesizers.github_actions import GitHubActionsSynthesizer

    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    ci_file = wf_dir / "ci.yml"
    detector = DriftDetector(tmp_path)

    # 1. Single-root multi-version + multi-OS matrix roundtrip
    single_matrix_ctx = ProjectContext(
        repo_name="matrix-py",
        repo_root=str(tmp_path),
        matrix_os=["ubuntu-latest", "macos-latest"],
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="pip",
                install_cmd="pip install -e '.[dev]'",
                test_cmd="pytest",
                matrix_versions=["3.10", "3.11", "3.12"],
            )
        ],
    )
    single_synth = GitHubActionsSynthesizer().synthesize(single_matrix_ctx)
    ci_file.write_text(single_synth[".github/workflows/ci.yml"], encoding="utf-8")
    assert detector.check_drift(single_matrix_ctx, single_synth) == []

    # Missing matrix versions (3.11, 3.12) and missing OS (macos-latest), with comment decoy
    ci_file.write_text(
        """name: CI
# macos-latest and python 3.11 3.12
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
""",
        encoding="utf-8",
    )
    single_findings = detector.check_drift(single_matrix_ctx, {".github/workflows/ci.yml": "dummy"})
    single_issues = [f.issue for f in single_findings]
    assert any("python 3.11" in i for i in single_issues)
    assert any("python 3.12" in i for i in single_issues)
    assert any("macos-latest" in i for i in single_issues)

    # 2. C++ cross-OS matrix roundtrip
    cpp_ctx = ProjectContext(
        repo_name="cpp-matrix",
        repo_root=str(tmp_path),
        matrix_os=["ubuntu-latest", "macos-latest"],
        languages=[
            LanguageContext(
                language="cpp",
                runtime_version="c++20",
                version_source="CMakeLists.txt",
                package_manager="cmake",
                install_cmd="cmake -B build -S .",
                build_cmd="cmake --build build",
                test_cmd="ctest --test-dir build --output-on-failure",
            )
        ],
    )
    cpp_synth = GitHubActionsSynthesizer().synthesize(cpp_ctx)
    ci_file.write_text(cpp_synth[".github/workflows/ci.yml"], encoding="utf-8")
    assert detector.check_drift(cpp_ctx, cpp_synth) == []

    # 3. Polyglot monorepo with per-package matrices and OS matrix roundtrip
    mono_matrix_ctx = ProjectContext(
        repo_name="mono-matrix",
        repo_root=str(tmp_path),
        is_monorepo=True,
        matrix_os=["ubuntu-latest", "macos-latest"],
        monorepo_packages=[
            MonorepoPackage(
                name="apps/web",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                runtime_version="22.x",
                version_source="package.json (engines)",
                install_cmd="pnpm i --frozen-lockfile",
                test_cmd="pnpm test",
                matrix_versions=["18.x", "20.x", "22.x"],
            ),
            MonorepoPackage(
                name="services/api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                version_source="pyproject.toml",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
                matrix_versions=["3.11", "3.12"],
            ),
        ],
    )
    mono_synth = GitHubActionsSynthesizer().synthesize(mono_matrix_ctx)
    ci_file.write_text(mono_synth[".github/workflows/ci.yml"], encoding="utf-8")
    assert detector.check_drift(mono_matrix_ctx, mono_synth) == []

    # Remove '22.x' from test-apps-web and 'macos-latest' from test-services-api
    ci_file.write_text(
        """name: CI
jobs:
  test-apps-web:
    runs-on: ${{ matrix.os }}
    defaults:
      run:
        working-directory: apps/web
    strategy:
      matrix:
        os: [ubuntu-latest]
        node-version: ['18.x', '20.x']
    steps:
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node-version }}
  test-services-api:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/api
    strategy:
      matrix:
        python-version: ['3.11', '3.12']
    steps:
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: ${{ matrix.python-version }}
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
""",
        encoding="utf-8",
    )
    mono_findings = detector.check_drift(mono_matrix_ctx, {".github/workflows/ci.yml": "dummy"})
    mono_issues = [f.issue for f in mono_findings]
    assert any("22.x" in i and "apps/web" in i for i in mono_issues)
    assert any("macos-latest" in i for i in mono_issues)


def test_phase3_drift_policy(tmp_path: Path):
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.drift import WorkflowASTInfo
    from heurix.synthesizers.github_actions import GitHubActionsSynthesizer

    # Backward-compatible 6-arg positional WorkflowASTInfo + new defaulted fields
    info_a = WorkflowASTInfo(set(), {"python": set()}, set(), set(), [], {})
    info_b = WorkflowASTInfo(set(), {"python": set()}, set(), set(), [], {})
    info_a.job_runs_on["test"] = {"ubuntu-latest"}
    info_a.job_steps["test"] = [(None, "step", "echo hi")]
    assert info_b.job_runs_on == {}
    assert info_b.job_steps == {}

    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    ci_file = wf_dir / "ci.yml"
    detector = DriftDetector(tmp_path)

    # 1. All test jobs explicitly override matrix_os + excluded services (postgresql alias) + disabled linters + injected steps
    full_override_policy = {
        "services": {"exclude": ["postgresql", "redis"]},
        "linters": {"enabled": False, "python": False},
        "ci": {
            "pin_actions": True,
            "action_shas": {"actions/cache": "0c45773b623bea8c8e75f6c82b208c3cf94ea4f9"},
            "runners": {
                "test-apps-web": "ubuntu-22.04",
                "test-services-api": "ubuntu-24.04-arm",
            },
            "steps": {
                "pre_test": [{"name": "Global Pre-Test", "run": "echo  global-pre"}],
                "post_test": [{"run": "echo global-post-only"}],
            },
        },
        "jobs": {
            "test-apps-web": {
                "runner": "ubuntu-24.04-arm",  # overrides [ci.runners].test-apps-web
                "pre_steps": [{"name": "Cache Web", "uses": "actions/cache@v4"}],
            },
            "test-services-api": {
                "post_steps": [{"name": "API Audit", "run": "echo api-audit"}],
            },
        },
    }

    mono_ctx = ProjectContext(
        repo_name="phase3-drift",
        repo_root=str(tmp_path),
        is_monorepo=True,
        matrix_os=["ubuntu-latest", "macos-latest"],
        monorepo_packages=[
            MonorepoPackage(
                name="apps/web",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                runtime_version="20.x",
                version_source=".nvmrc",
                install_cmd="pnpm i --frozen-lockfile",
                test_cmd="pnpm test",
                lint_cmd="pnpm lint",
            ),
            MonorepoPackage(
                name="services/api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                version_source=".python-version",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
                lint_cmd="uv run ruff check .",
            ),
        ],
        services=[
            ServiceRequirement(
                name="postgres",
                image="postgres:16-alpine",
                ports=[5432],
                source_file="services/api/pyproject.toml",
                package_path="services/api",
            ),
            ServiceRequirement(
                name="redis",
                image="redis:7-alpine",
                ports=[6379],
                source_file="docker-compose.yml",
            ),
            ServiceRequirement(
                name="mongodb",
                image="mongo:7",
                ports=[27017],
                source_file="apps/web/package.json",
                package_path="apps/web",
            ),
        ],
        policy_config=full_override_policy,
    )

    synth_files = GitHubActionsSynthesizer().synthesize(mono_ctx)
    ci_file.write_text(synth_files[".github/workflows/ci.yml"], encoding="utf-8")

    # Zero drift on freshly synthesized workflow (and with "dummy" synthesized_files)
    assert detector.check_drift(mono_ctx, synth_files) == []
    assert detector.check_drift(mono_ctx, {".github/workflows/ci.yml": "dummy"}) == []

    # AST info captures per-job runs_on and normalized job_steps
    ast_info = inspect_workflow_ast(YAML(typ="safe").load(ci_file.read_text(encoding="utf-8")))
    assert ast_info.job_runs_on["test-apps-web"] == {"ubuntu-24.04-arm"}
    assert ast_info.job_runs_on["test-services-api"] == {"ubuntu-24.04-arm"}
    assert ("actions/cache", "cache web", None) in ast_info.job_steps["test-apps-web"]
    assert (None, "global pre-test", "echo global-pre") in ast_info.job_steps["test-services-api"]
    assert (None, None, "echo global-post-only") in ast_info.job_steps["test-apps-web"]

    # 2. Positive drift detection when runner or injected steps drift on disk (using "dummy")
    drifted_workflow = """name: CI
jobs:
  test-apps-web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/web
    services:
      mongodb:
        image: mongo:7
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
      - name: Global Pre-Test
        run: echo global-pre
      # Missing: Cache Web (actions/cache), echo global-post-only
  test-services-api:
    runs-on: ubuntu-24.04-arm
    defaults:
      run:
        working-directory: services/api
    services:
      mongodb:
        image: mongo:7
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Global Pre-Test
        run: echo global-pre
      - run: echo global-post-only
      # Missing: API Audit
"""
    ci_file.write_text(drifted_workflow, encoding="utf-8")
    drift_findings = detector.check_drift(mono_ctx, {".github/workflows/ci.yml": "dummy"})
    drift_issues = [f.issue for f in drift_findings]
    assert any("test-apps-web" in i and "ubuntu-24.04-arm" in i for i in drift_issues)
    assert any("Cache Web" in i and "test-apps-web" in i for i in drift_issues)
    assert any("echo global-post-only" in i and "test-apps-web" in i for i in drift_issues)
    assert any("API Audit" in i and "test-services-api" in i for i in drift_issues)
    # Excluded services (postgres/redis) and disabled linters must NOT be flagged
    assert not any("postgres" in i.lower() or "redis" in i.lower() or "lint" in i.lower() for i in drift_issues)
    # matrix_os must NOT be flagged since all test jobs override runner
    assert not any("macos-latest" in i for i in drift_issues)

    # 3. Partial runner override: non-overridden test job still enforces matrix_os
    partial_policy = {
        "services": {"exclude": ["postgres", "redis"]},
        "linters": {"python": False},
        "ci": {
            "runners": {"test-apps-web": "ubuntu-24.04-arm"},
        },
    }
    partial_ctx = mono_ctx.model_copy(update={"policy_config": partial_policy})
    partial_synth = GitHubActionsSynthesizer().synthesize(partial_ctx)
    ci_file.write_text(partial_synth[".github/workflows/ci.yml"], encoding="utf-8")
    assert detector.check_drift(partial_ctx, {".github/workflows/ci.yml": "dummy"}) == []

    # Drop macos-latest from unoverridden test-services-api -> matrix_os drift must trigger
    ci_file.write_text(
        """name: CI
jobs:
  test-apps-web:
    runs-on: ubuntu-24.04-arm
    defaults:
      run:
        working-directory: apps/web
    services:
      mongodb:
        image: mongo:7
    steps:
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20.x'
  test-services-api:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/api
    services:
      mongodb:
        image: mongo:7
    steps:
      - uses: astral-sh/setup-uv@v5
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
""",
        encoding="utf-8",
    )
    partial_findings = detector.check_drift(partial_ctx, {".github/workflows/ci.yml": "dummy"})
    assert any("macos-latest" in f.issue for f in partial_findings)


def test_e2e_split_and_combined_zero_drift(tmp_path: Path):
    from heurix.core.context import MonorepoPackage
    from heurix.core.drift import _is_e2e_job_id
    from heurix.synthesizers.github_actions import GitHubActionsSynthesizer

    assert _is_e2e_job_id("test-e2e") is True
    assert _is_e2e_job_id("test-e2e-2") is True
    assert _is_e2e_job_id("test-apps-web-e2e") is True
    assert _is_e2e_job_id("test-apps-web-e2e-2") is True
    assert _is_e2e_job_id("web-e2e") is True
    assert _is_e2e_job_id("test") is False
    assert _is_e2e_job_id("test-apps-web") is False
    assert _is_e2e_job_id("e2e") is False

    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    ci_file = wf_dir / "ci.yml"
    detector = DriftDetector(tmp_path)
    syn = GitHubActionsSynthesizer()

    # 1. Split mode with [[ci.steps.pre_test]] and [[ci.steps.post_test]] + matrix_os -> zero drift
    split_ctx = ProjectContext(
        repo_name="e2e-drift-app",
        repo_root=str(tmp_path),
        matrix_os=["ubuntu-latest", "macos-latest"],
        split_e2e_jobs=True,
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
                test_cmd="npm test",
                unit_test_runner="vitest",
                e2e_test_runner="playwright",
                e2e_cmd="npm run test:e2e",
            )
        ],
        policy_config={
            "ci": {
                "steps": {
                    "pre_test": [{"name": "DB migrate", "run": "npm run db:migrate"}],
                    "post_test": [{"name": "Cleanup", "run": "echo done"}],
                }
            }
        },
    )

    split_files = syn.synthesize(split_ctx)
    ci_file.write_text(split_files[".github/workflows/ci.yml"], encoding="utf-8")
    assert detector.check_drift(split_ctx, split_files) == []
    # Also zero drift when hx check runs with split_e2e_jobs=None
    assert (
        detector.check_drift(split_ctx.model_copy(update={"split_e2e_jobs": None}), split_files)
        == []
    )

    # 2. Combined mode with [[ci.steps.pre_test]] + matrix_os -> zero drift
    combined_ctx = split_ctx.model_copy(update={"split_e2e_jobs": False})
    combined_files = syn.synthesize(combined_ctx)
    ci_file.write_text(combined_files[".github/workflows/ci.yml"], encoding="utf-8")
    assert detector.check_drift(combined_ctx, combined_files) == []
    assert (
        detector.check_drift(
            combined_ctx.model_copy(update={"split_e2e_jobs": None}), combined_files
        )
        == []
    )

    # 3. Explicit [jobs.test-e2e] pre_steps / runner override and OS matrix drift enforcement
    explicit_e2e_ctx = ProjectContext(
        repo_name="e2e-explicit",
        repo_root=str(tmp_path),
        is_monorepo=True,
        matrix_os=["ubuntu-latest", "macos-latest"],
        monorepo_packages=[
            MonorepoPackage(
                name="apps/web",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                runtime_version="20.x",
                version_source=".nvmrc",
                install_cmd="pnpm i --frozen-lockfile",
                test_cmd="pnpm test",
                unit_test_runner="vitest",
                e2e_test_runner="playwright",
                e2e_cmd="pnpm run test:e2e",
            ),
            MonorepoPackage(
                name="apps/admin",
                path="apps/admin",
                language="node",
                package_manager="pnpm",
                runtime_version="20.x",
                version_source=".nvmrc",
                install_cmd="pnpm i --frozen-lockfile",
                test_cmd="pnpm test",
                unit_test_runner="jest",
                e2e_test_runner="cypress",
                e2e_cmd="pnpm exec cypress run",
            ),
        ],
        policy_config={
            "ci": {
                "runners": {"test-e2e": "ubuntu-24.04"},
                "steps": {
                    "pre_test": [{"name": "Unit pre", "run": "echo unit"}],
                },
            },
            "jobs": {
                "test-e2e": {
                    "pre_steps": [{"name": "Seed E2E", "run": "echo seed"}],
                }
            },
        },
    )
    explicit_files = syn.synthesize(explicit_e2e_ctx)
    ci_file.write_text(explicit_files[".github/workflows/ci.yml"], encoding="utf-8")
    assert detector.check_drift(explicit_e2e_ctx, explicit_files) == []

    # Removing Seed E2E from test-e2e, changing test-e2e runner, or dropping macos-latest from test-e2e-2 triggers drift
    head_yml, tail_yml = explicit_files[".github/workflows/ci.yml"].split("  test-e2e-2:", 1)
    mutated_tail = tail_yml.replace("          - macos-latest\n", "", 1)
    ci_file.write_text(
        (head_yml + "  test-e2e-2:" + mutated_tail)
        .replace("      - name: Seed E2E\n        run: echo seed\n", "")
        .replace("runs-on: ubuntu-24.04", "runs-on: ubuntu-latest"),
        encoding="utf-8",
    )
    e2e_drift = detector.check_drift(explicit_e2e_ctx, {".github/workflows/ci.yml": "dummy"})
    e2e_issues = [f.issue for f in e2e_drift]
    assert any("Seed E2E" in i and "test-e2e" in i for i in e2e_issues)
    assert any("test-e2e" in i and "ubuntu-24.04" in i for i in e2e_issues)
    assert any("macos-latest" in i for i in e2e_issues)
    assert not any("Unit pre" in i and "test-e2e" in i for i in e2e_issues)
