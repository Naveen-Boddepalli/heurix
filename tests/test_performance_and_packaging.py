"""
Distribution packaging alignment and sub-second CLI latency benchmarks (NFR-04, NFR-02).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from ruamel.yaml import YAML

from heurix.core.validator import PreflightValidator

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
LATENCY_BUDGET_SECONDS = 1.0


def _resolve_hx_command() -> list[str]:
    """Return sibling hx console script path when installed, else module invocation."""
    candidate = Path(sys.executable).with_name("hx")
    if candidate.is_file():
        return [str(candidate)]
    return [sys.executable, "-m", "heurix.cli"]


def _time_cli_command(hx_cmd: list[str], args: list[str]) -> tuple[float, subprocess.CompletedProcess[str]]:
    """Execute a CLI subprocess invocation and return (elapsed_seconds, CompletedProcess)."""
    start = time.perf_counter()
    proc = subprocess.run(
        [*hx_cmd, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - start
    return elapsed, proc


def _create_polyglot_monorepo_fixture(root: Path) -> int:
    """
    Create a realistic polyglot monorepo fixture (pnpm + Node/Vitest/Playwright +
    Python/FastAPI/pytest + Dockerfile + nested .gitignore ignoring 300+ build artifacts
    alongside 200+ active source files) and return total file count on disk.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "pnpm-workspace.yaml").write_text(
        'packages:\n  - "apps/*"\n  - "services/*"\n',
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(
        "node_modules/\ndist/\n__pycache__/\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "polyglot-monorepo",
                "private": True,
                "packageManager": "pnpm@9.0.0",
            }
        ),
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(
        "FROM node:20-alpine\nEXPOSE 3000\n",
        encoding="utf-8",
    )

    # Node + Vitest + Playwright package (110 active files + 240 ignored artifacts)
    web = root / "apps" / "web"
    (web / "src" / "components").mkdir(parents=True)
    (web / ".nvmrc").write_text("20\n", encoding="utf-8")
    (web / "package.json").write_text(
        json.dumps(
            {
                "name": "@polyglot/web",
                "scripts": {
                    "build": "vite build",
                    "test": "vitest run",
                    "test:e2e": "playwright test",
                },
                "dependencies": {"react": "^18.3.0"},
                "devDependencies": {
                    "vitest": "^1.5.0",
                    "@playwright/test": "^1.48.0",
                },
            }
        ),
        encoding="utf-8",
    )
    (web / ".gitignore").write_text("dist/\n.vite/\n", encoding="utf-8")
    for idx in range(110):
        (web / "src" / "components" / f"comp_{idx}.tsx").write_text(
            f"export const Component{idx} = () => null;\n",
            encoding="utf-8",
        )
    (web / "node_modules" / "pkg").mkdir(parents=True)
    for idx in range(180):
        (web / "node_modules" / "pkg" / f"mod_{idx}.js").write_text(
            "module.exports = {};\n",
            encoding="utf-8",
        )
    (web / "dist").mkdir(parents=True)
    for idx in range(60):
        (web / "dist" / f"bundle_{idx}.js").write_text("// bundle\n", encoding="utf-8")

    # Python + FastAPI + pytest service (110 active files + 120 ignored artifacts)
    api = root / "services" / "api"
    (api / "app").mkdir(parents=True)
    (api / "tests").mkdir(parents=True)
    (api / ".python-version").write_text("3.12\n", encoding="utf-8")
    (api / "pyproject.toml").write_text(
        '[project]\nname = "api-service"\nversion = "0.1.0"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["fastapi>=0.110.0", "redis>=5.0.0"]\n\n'
        '[project.optional-dependencies]\ndev = ["pytest>=8.0.0"]\n',
        encoding="utf-8",
    )
    (api / ".gitignore").write_text("build_artifacts/\n.pytest_cache/\n", encoding="utf-8")
    for idx in range(110):
        (api / "app" / f"module_{idx}.py").write_text(
            f"def compute_{idx}(value: int) -> int:\n    return value + {idx}\n",
            encoding="utf-8",
        )
    (api / "tests" / "test_api.py").write_text(
        "def test_health() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (api / "build_artifacts").mkdir(parents=True)
    for idx in range(120):
        (api / "build_artifacts" / f"artifact_{idx}.txt").write_text(
            "ignored\n",
            encoding="utf-8",
        )

    return sum(1 for path in root.rglob("*") if path.is_file())


def test_packaging_wheel_homebrew_docker_and_workflows(tmp_path: Path) -> None:
    """
    Offline verification of wheel templates/metadata, Homebrew formula, Docker context,
    install.sh, Makefile, and PyPI/Docker release workflows.
    """
    # 1. pyproject.toml metadata source of truth
    pyproject_data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject_data["project"]
    assert project["name"] == "heurix"
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.10"
    assert project["scripts"] == {"hx": "heurix.cli:app", "heurix": "heurix.cli:app"}
    assert "jinja2>=3.1.6" in project["dependencies"]

    # 2. Offline wheel build & contents check (templates/**/*.j2 + Requires-Dist)
    wheel_dir = tmp_path / "wheelhouse"
    wheel_dir.mkdir(parents=True)
    wheel_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(wheel_dir),
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert wheel_proc.returncode == 0, f"pip wheel failed:\n{wheel_proc.stdout}\n{wheel_proc.stderr}"

    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, f"Expected single built wheel, found: {wheels}"

    template_root = REPO_ROOT / "src" / "heurix" / "templates"
    disk_templates = sorted(
        path.relative_to(REPO_ROOT / "src").as_posix()
        for path in template_root.rglob("*.j2")
    )
    assert len(disk_templates) == 9
    expected_templates = {
        "heurix/templates/workflows/ci.yml.j2",
        "heurix/templates/dependabot/dependabot.yml.j2",
        "heurix/templates/k8s/deployment.yaml.j2",
        "heurix/templates/k8s/service.yaml.j2",
        "heurix/templates/k8s/ingress.yaml.j2",
        "heurix/templates/k8s/configmap.yaml.j2",
        "heurix/templates/k8s/hpa.yaml.j2",
        "heurix/templates/k8s/kind-config.yaml.j2",
        "heurix/templates/macros/actions.j2",
    }
    assert set(disk_templates) == expected_templates

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())
        for tmpl in disk_templates:
            assert tmpl in names, f"Missing bundled template inside wheel: {tmpl}"

        metadata_names = [n for n in names if n.endswith(".dist-info/METADATA")]
        assert len(metadata_names) == 1
        metadata_text = zf.read(metadata_names[0]).decode("utf-8")
        assert "Name: heurix" in metadata_text
        assert f"Version: {project['version']}" in metadata_text
        assert "Requires-Python: >=3.10" in metadata_text
        assert "Requires-Dist: jinja2>=3.1.6" in metadata_text
        assert "Requires-Dist: typer>=0.12.0" in metadata_text

        entry_points_names = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
        assert len(entry_points_names) == 1
        ep_text = zf.read(entry_points_names[0]).decode("utf-8")
        assert "hx = heurix.cli:app" in ep_text
        assert "heurix = heurix.cli:app" in ep_text

    # 3. Homebrew formula alignment + ruby -c syntax check
    formula_path = REPO_ROOT / "packaging" / "homebrew" / "heurix.rb"
    formula_text = formula_path.read_text(encoding="utf-8")
    assert f'desc "{project["description"]}"' in formula_text
    assert f'homepage "{project["urls"]["Homepage"]}"' in formula_text
    assert f"heurix-{project['version']}.tar.gz" in formula_text
    assert 'license "MIT"' in formula_text
    assert "virtualenv_install_with_resources" in formula_text
    assert "homebrew-pypi-poet" in formula_text
    assert 'sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"' in formula_text
    # Ensure broken assertion ('Heurix (hx)' checked against --help) is fixed
    assert 'assert_match "Heurix (hx)", shell_output("#{bin}/hx --help")' not in formula_text
    assert 'assert_match "Heurix (hx)", shell_output("#{bin}/hx --version")' in formula_text
    assert 'assert_match "Deterministic Codebase Scanner", shell_output("#{bin}/hx --help")' in formula_text
    assert "hx scan --path" in formula_text
    assert '"python"' in formula_text

    ruby_bin = shutil.which("ruby")
    if ruby_bin:
        ruby_proc = subprocess.run(
            [ruby_bin, "-c", str(formula_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert ruby_proc.returncode == 0, f"ruby -c failed:\n{ruby_proc.stderr}"
        assert "Syntax OK" in ruby_proc.stdout

    # 4. Docker build context (.dockerignore) + Dockerfile + Makefile parity
    dockerignore_lines = {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for required_ignore in (
        ".git",
        ".venv",
        "tests/",
        "site/",
        ".planning/",
        "docs/",
        "heurix_source_dump.txt",
    ):
        assert required_ignore in dockerignore_lines, f"Missing {required_ignore} in .dockerignore"
    for must_not_ignore in ("src", "src/", "src/heurix/templates/", "pyproject.toml", "README.md"):
        assert must_not_ignore not in dockerignore_lines

    dockerfile_text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY pyproject.toml README.md ./" in dockerfile_text
    assert "COPY src ./src" in dockerfile_text
    assert "pip wheel --no-deps --no-build-isolation --no-cache-dir -w /app/dist ." in dockerfile_text
    assert "useradd -u 10001" in dockerfile_text
    assert "USER heurix" in dockerfile_text
    assert 'ENTRYPOINT ["hx"]' in dockerfile_text

    makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "wheel --no-deps --no-build-isolation" in makefile_text

    # 5. install.sh parity & bash syntax check
    install_path = REPO_ROOT / "install.sh"
    install_text = install_path.read_text(encoding="utf-8")
    assert "PY_MAJOR" in install_text and "PY_MINOR" in install_text
    assert "-lt 10" in install_text
    assert '${BIN_DIR}/hx' in install_text
    assert '${BIN_DIR}/heurix' in install_text
    bash_bin = shutil.which("bash")
    if bash_bin:
        bash_proc = subprocess.run(
            [bash_bin, "-n", str(install_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert bash_proc.returncode == 0, f"bash -n install.sh failed:\n{bash_proc.stderr}"

    # 6. GitHub release workflows schema validation + post-build wheel smoke test
    validator = PreflightValidator()
    yaml = YAML(typ="safe")

    for wf_rel in (
        ".github/workflows/publish-pypi.yml",
        ".github/workflows/docker-publish.yml",
        ".github/workflows/ci.yml",
    ):
        wf_text = (REPO_ROOT / wf_rel).read_text(encoding="utf-8")
        is_valid, errors = validator.validate(wf_rel, wf_text)
        assert is_valid, f"Workflow validation failed for {wf_rel}: {errors}"

    pypi_wf = yaml.load((REPO_ROOT / ".github/workflows/publish-pypi.yml").read_text(encoding="utf-8"))
    build_steps = pypi_wf["jobs"]["build"]["steps"]
    step_runs = "\n".join(str(step.get("run", "")) for step in build_steps)
    step_names = [str(step.get("name", "")) for step in build_steps]
    assert any("smoke" in name.lower() for name in step_names), "Missing wheel smoke test step in publish-pypi.yml"
    assert "dist/*.whl" in step_runs
    assert "hx" in step_runs and "--version" in step_runs and "--help" in step_runs
    assert "scan" in step_runs and "generate" in step_runs and "--dry-run" in step_runs

    docker_wf_text = (REPO_ROOT / ".github/workflows/docker-publish.yml").read_text(encoding="utf-8")
    for trigger_path in ("Dockerfile", ".dockerignore", "pyproject.toml", "src/**"):
        assert trigger_path in docker_wf_text


def test_cli_subsecond_latency_benchmarks(tmp_path: Path) -> None:
    """
    Verify NFR-04 sub-second (< 1.0s) CLI subprocess latency on cold startup,
    the Heurix repository root, and a 500+ file polyglot monorepo fixture.
    """
    hx_cmd = _resolve_hx_command()

    # 0. Cold subprocess CLI startup check (--version)
    startup_elapsed, startup_proc = _time_cli_command(hx_cmd, ["--version"])
    assert startup_proc.returncode == 0, startup_proc.stderr
    assert "Heurix (hx)" in startup_proc.stdout
    assert startup_elapsed < LATENCY_BUDGET_SECONDS, (
        f"hx --version took {startup_elapsed:.3f}s (budget < {LATENCY_BUDGET_SECONDS:.1f}s)"
    )

    # 1. Heurix repository root benchmarks
    repo_benchmarks = [
        (["scan", "--path", str(REPO_ROOT)], '"python"'),
        (["check", "--path", str(REPO_ROOT)], "Zero Drift Detected"),
        (["generate", "--path", str(REPO_ROOT), "--dry-run", "--yes"], "Dry run completed"),
    ]
    for args, expected_text in repo_benchmarks:
        elapsed, proc = _time_cli_command(hx_cmd, args)
        assert proc.returncode == 0, f"{args} failed:\n{proc.stdout}\n{proc.stderr}"
        assert expected_text in proc.stdout
        assert elapsed < LATENCY_BUDGET_SECONDS, (
            f"Repo root {args} took {elapsed:.3f}s (budget < {LATENCY_BUDGET_SECONDS:.1f}s)"
        )

    # 2. Realistic 500+ file polyglot monorepo fixture benchmarks
    fixture_root = tmp_path / "polyglot_monorepo"
    total_files = _create_polyglot_monorepo_fixture(fixture_root)
    assert total_files >= 500, f"Expected 500+ files in monorepo fixture, got {total_files}"

    gen_proc = subprocess.run(
        [*hx_cmd, "generate", "--path", str(fixture_root), "--yes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert gen_proc.returncode == 0, f"Fixture generate failed:\n{gen_proc.stdout}\n{gen_proc.stderr}"
    assert (fixture_root / ".github" / "workflows" / "ci.yml").is_file()

    fixture_benchmarks = [
        (["scan", "--path", str(fixture_root)], '"is_monorepo": true'),
        (["check", "--path", str(fixture_root)], "Zero Drift Detected"),
        (["generate", "--path", str(fixture_root), "--dry-run", "--yes"], "Dry run completed"),
    ]
    for args, expected_text in fixture_benchmarks:
        elapsed, proc = _time_cli_command(hx_cmd, args)
        assert proc.returncode == 0, f"Fixture {args} failed:\n{proc.stdout}\n{proc.stderr}"
        assert expected_text in proc.stdout
        assert elapsed < LATENCY_BUDGET_SECONDS, (
            f"Fixture {args} took {elapsed:.3f}s (budget < {LATENCY_BUDGET_SECONDS:.1f}s)"
        )
