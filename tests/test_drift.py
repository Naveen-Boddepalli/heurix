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


