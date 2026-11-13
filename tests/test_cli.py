"""
Tests for Heurix CLI Commands.
"""

from __future__ import annotations

from pathlib import Path
from typer.testing import CliRunner
from heurix.cli import app

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.2.0" in result.stdout


def test_cli_init(tmp_path: Path):
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".heurix.toml").exists()


def test_cli_scan_json(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
    result = runner.invoke(app, ["scan", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert '"repo_name"' in result.stdout
    assert '"python"' in result.stdout


def test_cli_generate_dry_run(tmp_path: Path):
    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    result = runner.invoke(app, ["generate", "--path", str(tmp_path), "--dry-run", "--yes"])
    assert result.exit_code == 0
    assert "Dry run completed" in result.stdout
    assert not (tmp_path / ".github" / "workflows" / "ci.yml").exists()


def test_cli_generate_and_drift(tmp_path: Path):
    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    # Generate actual files
    gen_result = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_result.exit_code == 0
    assert (tmp_path / ".github" / "workflows" / "ci.yml").exists()

    # Check drift -> should be 0 drift
    check_result = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert check_result.exit_code == 0
    assert "Zero Drift" in check_result.stdout


def test_cli_heurix_toml_overrides(tmp_path: Path):
    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / ".heurix.toml").write_text(
        """
[engine]
runner = "ubuntu-22.04"

[ci]
include_dependabot = false
include_k8s = false

[overrides]
python = "3.11"
""",
        encoding="utf-8",
    )

    gen_result = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_result.exit_code == 0

    ci_file = tmp_path / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists()
    content = ci_file.read_text(encoding="utf-8")

    # Runner override applied
    assert "runs-on: ubuntu-22.04" in content
    # Python override applied
    assert "python-version: '3.11'" in content or 'python-version: "3.11"' in content or "python-version: 3.11" in content
    # Dependabot skipped via include_dependabot = false
    assert not (tmp_path / ".github" / "dependabot.yml").exists()
    # K8s skipped via include_k8s = false
    assert not (tmp_path / "k8s").exists()


def test_cli_diff_prompt_loop(tmp_path: Path, monkeypatch):
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    existing_ci = ci_dir / "ci.yml"
    existing_ci.write_text("name: Old CI\njobs: {}\n", encoding="utf-8")

    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    # Simulate user choosing 'diff' first, then 'skip'
    responses = ["diff", "skip"]
    diff_called = []

    def mock_prompt(rel_path, non_interactive=False):
        return responses.pop(0)

    def mock_show_diff(rel_path, old_content, new_content):
        diff_called.append(rel_path)

    monkeypatch.setattr("heurix.cli.prompt_conflict_resolution", mock_prompt)
    monkeypatch.setattr("heurix.cli.show_diff", mock_show_diff)

    result = runner.invoke(app, ["generate", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert len(diff_called) == 1
    # Because user answered 'skip' on re-prompt, existing content is untouched
    assert existing_ci.read_text(encoding="utf-8") == "name: Old CI\njobs: {}\n"


def test_cli_cpp_cmake_generate_and_zero_drift(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\nproject(demo)\nset(CMAKE_CXX_STANDARD 17)\n",
        encoding="utf-8",
    )
    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 0

    check_res = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert check_res.exit_code == 0
    assert "Zero Drift" in check_res.stdout


def test_cli_non_destructive_policy_disabled(tmp_path: Path):
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    existing_ci = ci_dir / "ci.yml"
    existing_ci.write_text(
        """name: Old CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      # @heurix:preserve
      - name: Old Custom Step
        run: echo old
""",
        encoding="utf-8",
    )

    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / ".heurix.toml").write_text(
        """
[engine]
non_destructive = false
""",
        encoding="utf-8",
    )

    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 0

    # With non_destructive = false, SmartMerger is bypassed and old preserved step is overwritten
    content = existing_ci.read_text(encoding="utf-8")
    assert "Old Custom Step" not in content


def test_path_traversal_resolve_safe_path(tmp_path: Path):
    import pytest
    from heurix.cli import resolve_safe_path

    repo = tmp_path / "repo"
    repo.mkdir()

    # Valid repository paths resolve cleanly inside repo
    ci_dest = resolve_safe_path(repo, ".github/workflows/ci.yml")
    assert ci_dest == repo.resolve() / ".github" / "workflows" / "ci.yml"
    k8s_dest = resolve_safe_path(repo, "k8s/deployment.yaml")
    assert k8s_dest == repo.resolve() / "k8s" / "deployment.yaml"

    # Traversal and absolute escape inputs must raise ValueError
    for bad_path in ("../../evil.yml", "../outside.yaml", "a/b/../../../evil.yml", "/etc/passwd"):
        with pytest.raises(ValueError, match="Path traversal security violation"):
            resolve_safe_path(repo, bad_path)

    # Symlink pointing outside repository root must also be rejected
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    escape_link = repo / "escape_link"
    escape_link.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        resolve_safe_path(repo, "escape_link/evil.yml")


def test_path_traversal_blocked_in_generate_and_diff(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".python-version").write_text("3.12", encoding="utf-8")
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    outside_target = tmp_path / "outside_evil.yml"

    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            "../outside_evil.yml": "evil: true\n",
        },
    )

    gen_res = runner.invoke(app, ["generate", "--path", str(repo), "--yes"])
    assert gen_res.exit_code == 1
    normalized_gen = " ".join(gen_res.stdout.split())
    assert "Path traversal security violation" in normalized_gen
    assert not outside_target.exists()

    diff_res = runner.invoke(app, ["diff", "--path", str(repo)])
    assert diff_res.exit_code == 1
    normalized_diff = " ".join(diff_res.stdout.split())
    assert "Path traversal security violation" in normalized_diff
    assert not outside_target.exists()

    # Also test absolute destination injection
    abs_target = tmp_path / "abs_evil.yml"
    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            str(abs_target): "evil: true\n",
        },
    )
    abs_res = runner.invoke(app, ["generate", "--path", str(repo), "--yes"])
    assert abs_res.exit_code == 1
    assert not abs_target.exists()


def test_cli_yaml_syntax_error_exits_cleanly(tmp_path: Path):
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    malformed_content = "name: Broken CI\njobs:\n  test: [unclosed\n"
    ci_file = ci_dir / "ci.yml"
    ci_file.write_text(malformed_content, encoding="utf-8")

    (tmp_path / ".python-version").write_text("3.12", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 1
    assert isinstance(gen_res.exception, SystemExit)
    normalized_out = " ".join(gen_res.stdout.split())
    assert "YAML Syntax Error" in normalized_out
    assert ".github/workflows/ci.yml" in normalized_out
    assert "Traceback" not in gen_res.stdout
    # Existing malformed file must NOT be silently overwritten
    assert ci_file.read_text(encoding="utf-8") == malformed_content

    diff_res = runner.invoke(app, ["diff", "--path", str(tmp_path)])
    assert diff_res.exit_code == 1
    assert isinstance(diff_res.exception, SystemExit)
    assert "YAML Syntax Error" in " ".join(diff_res.stdout.split())
    assert "Traceback" not in diff_res.stdout


def test_cli_monorepo_nested_gitignore_and_matrix_roundtrip(tmp_path: Path):
    import json
    import re
    from ruamel.yaml import YAML

    # Build polyglot monorepo fixture:
    # - pnpm-workspace.yaml + pnpm-lock.yaml
    # - apps/web (Node + nested .gitignore hiding local_build/package.json)
    # - services/api (Python + classifiers 3.11/3.12 + fastapi/pytest)
    # - .heurix.toml [matrix] os = ["ubuntu-latest", "macos-latest"]
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    web_dir = tmp_path / "apps" / "web"
    web_dir.mkdir(parents=True)
    (web_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "@mono/web",
                "scripts": {"build": "vite build", "test": "vitest run"},
            }
        ),
        encoding="utf-8",
    )
    (web_dir / ".gitignore").write_text("local_build/\n", encoding="utf-8")
    ignored_build = web_dir / "local_build"
    ignored_build.mkdir()
    (ignored_build / "package.json").write_text('{"name": "ignored-build"}', encoding="utf-8")

    api_dir = tmp_path / "services" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "pyproject.toml").write_text(
        """[project]
name = "api"
version = "0.1.0"
classifiers = [
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dependencies = ["fastapi", "pytest"]
""",
        encoding="utf-8",
    )

    (tmp_path / ".heurix.toml").write_text(
        """[matrix]
os = ["ubuntu-latest", "macos-latest"]
""",
        encoding="utf-8",
    )

    # 1. hx scan
    scan_res = runner.invoke(
        app,
        ["scan", "--path", str(tmp_path)],
        env={"COLUMNS": "400", "NO_COLOR": "1"},
    )
    assert scan_res.exit_code == 0, scan_res.stdout
    clean_out = re.sub(r"\x1b\[[0-9;]*m", "", scan_res.stdout)
    scan_data = json.loads(clean_out)

    assert scan_data["is_monorepo"] is True
    assert scan_data["matrix_os"] == ["ubuntu-latest", "macos-latest"]
    pkg_paths = [p["path"] for p in scan_data["monorepo_packages"]]
    assert pkg_paths == ["apps/web", "services/api"]
    assert all("local_build" not in p for p in pkg_paths)

    api_pkg = next(p for p in scan_data["monorepo_packages"] if p["path"] == "services/api")
    assert api_pkg["matrix_versions"] == ["3.11", "3.12"]

    # 2. hx generate --yes
    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 0, gen_res.stdout

    ci_file = tmp_path / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists()
    doc = YAML(typ="safe").load(ci_file.read_text(encoding="utf-8"))

    assert doc["on"]["push"]["paths"] == ["apps/web/**", "services/api/**"]
    assert doc["on"]["pull_request"]["paths"] == ["apps/web/**", "services/api/**"]
    assert set(doc["jobs"].keys()) == {"test-apps-web", "test-services-api"}

    web_job = doc["jobs"]["test-apps-web"]
    assert web_job["defaults"]["run"]["working-directory"] == "apps/web"
    assert web_job["runs-on"] == "${{ matrix.os }}"
    assert web_job["strategy"] == {
        "fail-fast": False,
        "matrix": {"os": ["ubuntu-latest", "macos-latest"]},
    }

    api_job = doc["jobs"]["test-services-api"]
    assert api_job["defaults"]["run"]["working-directory"] == "services/api"
    assert api_job["runs-on"] == "${{ matrix.os }}"
    assert api_job["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "os": ["ubuntu-latest", "macos-latest"],
            "python-version": ["3.11", "3.12"],
        },
    }

    # 3. hx check -> Zero Drift Detected
    check_res = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert check_res.exit_code == 0, check_res.stdout
    assert "Zero Drift Detected" in check_res.stdout


def test_cli_monorepo_smart_merge_preserves_custom_steps(tmp_path: Path):
    import json
    from ruamel.yaml import YAML

    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n", encoding="utf-8")
    (tmp_path / "vercel.json").write_text('{"name": "mono-web"}', encoding="utf-8")

    web_dir = tmp_path / "apps" / "web"
    web_dir.mkdir(parents=True)
    (web_dir / "package.json").write_text(
        json.dumps({"name": "web", "scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )

    api_dir = tmp_path / "services" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "pyproject.toml").write_text(
        """[project]
name = "api"
version = "0.1.0"
classifiers = [
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dependencies = ["pytest"]
""",
        encoding="utf-8",
    )

    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    ci_file = ci_dir / "ci.yml"
    ci_file.write_text(
        """name: CI
on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main
jobs:
  test-apps-web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/old
    steps:
      - uses: actions/checkout@v3
      # @heurix:preserve
      - name: Custom Web Security Audit
        run: pnpm audit
  test-services-api:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      # @heurix:preserve
      - name: Custom API Coverage Upload
        run: echo upload-cov
  deploy_vercel:
    name: Deploy to Vercel
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # @heurix:preserve
      - name: Notify Deploy
        run: echo notify-deploy
  custom_notify:
    runs-on: ubuntu-latest
    steps:
      - name: Custom Notify Job
        run: echo custom-notify
""",
        encoding="utf-8",
    )

    (tmp_path / ".heurix.toml").write_text(
        """[matrix]
os = ["ubuntu-latest", "macos-latest"]
""",
        encoding="utf-8",
    )

    # First hx generate over customized multi-job workflow
    gen_res = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_res.exit_code == 0, gen_res.stdout

    doc = YAML(typ="safe").load(ci_file.read_text(encoding="utf-8"))
    assert doc["on"]["push"]["paths"] == ["apps/web/**", "services/api/**"]
    assert doc["on"]["pull_request"]["paths"] == ["apps/web/**", "services/api/**"]

    web_job = doc["jobs"]["test-apps-web"]
    assert web_job["defaults"]["run"]["working-directory"] == "apps/web"
    assert web_job["runs-on"] == "${{ matrix.os }}"
    assert web_job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "macos-latest"]
    assert any(s.get("name") == "Custom Web Security Audit" for s in web_job["steps"])

    api_job = doc["jobs"]["test-services-api"]
    assert api_job["defaults"]["run"]["working-directory"] == "services/api"
    assert api_job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    assert any(s.get("name") == "Custom API Coverage Upload" for s in api_job["steps"])

    assert doc["jobs"]["deploy_vercel"]["needs"] == ["test-apps-web", "test-services-api"]
    assert any(s.get("name") == "Notify Deploy" for s in doc["jobs"]["deploy_vercel"]["steps"])
    assert "custom_notify" in doc["jobs"]

    check_res = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert check_res.exit_code == 0, check_res.stdout
    assert "Zero Drift Detected" in check_res.stdout

    # Collapse matrix via scalar override and re-run hx generate -> stale strategy removed, preserve kept
    (tmp_path / ".heurix.toml").write_text(
        """[engine]
runner = "ubuntu-latest"

[overrides]
python = "3.12"
""",
        encoding="utf-8",
    )
    gen_collapse = runner.invoke(app, ["generate", "--path", str(tmp_path), "--yes"])
    assert gen_collapse.exit_code == 0, gen_collapse.stdout

    collapsed_doc = YAML(typ="safe").load(ci_file.read_text(encoding="utf-8"))
    assert "strategy" not in collapsed_doc["jobs"]["test-apps-web"]
    assert "strategy" not in collapsed_doc["jobs"]["test-services-api"]
    assert collapsed_doc["jobs"]["test-apps-web"]["runs-on"] == "ubuntu-latest"
    assert collapsed_doc["jobs"]["test-services-api"]["runs-on"] == "ubuntu-latest"
    assert any(
        s.get("name") == "Custom Web Security Audit"
        for s in collapsed_doc["jobs"]["test-apps-web"]["steps"]
    )
    assert any(
        s.get("name") == "Custom API Coverage Upload"
        for s in collapsed_doc["jobs"]["test-services-api"]["steps"]
    )

    check_collapsed = runner.invoke(app, ["check", "--path", str(tmp_path)])
    assert check_collapsed.exit_code == 0, check_collapsed.stdout
    assert "Zero Drift Detected" in check_collapsed.stdout


def test_cli_phase3_policy_and_template_override(tmp_path: Path):
    import json
    import re
    import sys
    from ruamel.yaml import YAML
    from heurix.core.policy import parse_heurix_policy

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    # 1. hx init emits valid TOML documenting Phase 3 policy sections cleanly
    init_repo = tmp_path / "init_repo"
    init_repo.mkdir()
    init_res = runner.invoke(app, ["init", "--path", str(init_repo)])
    assert init_res.exit_code == 0, init_res.stdout
    init_toml_path = init_repo / ".heurix.toml"
    assert init_toml_path.exists()
    init_text = init_toml_path.read_text(encoding="utf-8")

    for section_marker in (
        "templates_dir",
        "[ci.runners]",
        "[[ci.steps.pre_test]]",
        "[[ci.steps.post_test]]",
        "[jobs.",
        "[services]",
        "[env]",
        "[secrets]",
        "[linters]",
        "[kubernetes]",
        "[k8s]",
        "hpa",
        "liveness_probe",
        "readiness_probe",
        "resources",
    ):
        assert section_marker in init_text, f"Missing '{section_marker}' in hx init template"

    parsed_init = tomllib.loads(init_text)
    _, init_warnings = parse_heurix_policy(parsed_init)
    assert init_warnings == []

    # 2. End-to-end polyglot FastAPI + Docker + postgres/redis + Vercel repo with Phase 3 overrides & local template
    app_repo = tmp_path / "app_repo"
    app_repo.mkdir()
    (app_repo / "pyproject.toml").write_text(
        """[project]
name = "fastapi-svc"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn>=0.29.0",
    "psycopg2-binary>=2.9.9",
    "redis>=5.0.0",
    "pytest>=8.0.0",
    "ruff>=0.4.0",
]
""",
        encoding="utf-8",
    )
    (app_repo / "Dockerfile").write_text(
        "FROM python:3.12-slim\nEXPOSE 8000\nCMD [\"uvicorn\", \"app:app\"]\n",
        encoding="utf-8",
    )
    (app_repo / "vercel.json").write_text('{"name": "fastapi-svc"}', encoding="utf-8")

    # Repo-local template override for k8s/service.yaml.j2
    local_k8s_tpl_dir = app_repo / ".heurix" / "templates" / "k8s"
    local_k8s_tpl_dir.mkdir(parents=True)
    (local_k8s_tpl_dir / "service.yaml.j2").write_text(
        """# Custom local service override
apiVersion: v1
kind: Service
metadata:
  name: {{ service_name | yaml_scalar }}
{% if namespace %}
  namespace: {{ namespace | yaml_scalar }}
{% endif %}
  labels:
    app: {{ app_name | yaml_scalar }}
spec:
  type: {{ service_type | yaml_scalar }}
  selector:
    app: {{ app_name | yaml_scalar }}
  ports:
{% for p in ports %}
    - protocol: {{ p.protocol | yaml_scalar }}
      port: {{ p.port }}
      targetPort: {{ p.targetPort }}
{% endfor %}
""",
        encoding="utf-8",
    )

    toml_path = app_repo / ".heurix.toml"
    toml_path.write_text(
        """[engine]
runner = "ubuntu-latest"
non_destructive = true

[ci]
include_dependabot = true
include_k8s = true

[ci.runners]
test = "ubuntu-24.04-arm"
deploy_vercel = "ubuntu-22.04"

[[ci.steps.pre_test]]
name = "Verify schema"
run = "echo schema ok"

[services]
exclude = ["redis"]

[env]
APP_MODE = "staging"
DATABASE_URL = "postgres://blocked-secret"

[secrets]
test = ["TEST_API_TOKEN", "VERCEL_TOKEN"]
deploy = ["VERCEL_TOKEN"]

[linters]
python = false

[kubernetes]
replicas = 3
namespace = "staging"
service_type = "LoadBalancer"

[kubernetes.resources.requests]
cpu = "150m"
memory = "320Mi"

[kubernetes.liveness_probe]
type = "httpGet"
path = "/healthz"
port = 8000

[kubernetes.hpa]
enabled = true
min_replicas = 2
max_replicas = 8
target_cpu_utilization = 75
""",
        encoding="utf-8",
    )

    # 2a. hx scan outputs policy-mutated IR
    scan_res = runner.invoke(
        app,
        ["scan", "--path", str(app_repo)],
        env={"COLUMNS": "400", "NO_COLOR": "1"},
    )
    assert scan_res.exit_code == 0, scan_res.stdout
    scan_data = json.loads(re.sub(r"\x1b\[[0-9;]*m", "", scan_res.stdout))

    svc_names = [s["name"] for s in scan_data["services"]]
    assert "postgres" in svc_names
    assert "redis" not in svc_names
    assert scan_data["env_vars"].get("APP_MODE") == "staging"
    assert "DATABASE_URL" not in scan_data["env_vars"]
    assert "TEST_API_TOKEN" in scan_data["test_secrets"]
    assert "VERCEL_TOKEN" not in scan_data["test_secrets"]
    assert "VERCEL_TOKEN" in scan_data["deployment_secrets"]
    assert scan_data["languages"][0]["lint_cmd"] is None

    # 2b. hx generate --yes synthesizes CI, Dependabot, K8s + HPA + local template override
    gen_res = runner.invoke(app, ["generate", "--path", str(app_repo), "--yes"])
    assert gen_res.exit_code == 0, gen_res.stdout

    ci_path = app_repo / ".github" / "workflows" / "ci.yml"
    dep_path = app_repo / ".github" / "dependabot.yml"
    k8s_dep_path = app_repo / "k8s" / "deployment.yaml"
    k8s_svc_path = app_repo / "k8s" / "service.yaml"
    k8s_cm_path = app_repo / "k8s" / "configmap.yaml"
    k8s_hpa_path = app_repo / "k8s" / "hpa.yaml"

    for expected_file in (ci_path, dep_path, k8s_dep_path, k8s_svc_path, k8s_cm_path, k8s_hpa_path):
        assert expected_file.exists(), f"Missing generated file: {expected_file}"

    yaml = YAML(typ="safe")
    ci_doc = yaml.load(ci_path.read_text(encoding="utf-8"))
    assert ci_doc["jobs"]["test"]["runs-on"] == "ubuntu-24.04-arm"
    assert ci_doc["jobs"]["deploy_vercel"]["runs-on"] == "ubuntu-22.04"
    assert "postgres" in ci_doc["jobs"]["test"]["services"]
    assert "redis" not in ci_doc["jobs"]["test"]["services"]
    test_steps = ci_doc["jobs"]["test"]["steps"]
    assert any(s.get("name") == "Verify schema" for s in test_steps)
    assert not any("lint" in (s.get("name") or "").lower() for s in test_steps)
    run_test_step = next(s for s in test_steps if s.get("name") == "Run tests (python)")
    assert run_test_step["env"]["APP_MODE"] == "staging"
    assert run_test_step["env"]["TEST_API_TOKEN"] == "${{ secrets.TEST_API_TOKEN }}"
    assert "DATABASE_URL" not in run_test_step["env"]
    assert "VERCEL_TOKEN" not in run_test_step["env"]

    svc_raw = k8s_svc_path.read_text(encoding="utf-8")
    assert "# Custom local service override" in svc_raw
    svc_doc = yaml.load(svc_raw)
    assert svc_doc["metadata"]["namespace"] == "staging"
    assert svc_doc["spec"]["type"] == "LoadBalancer"

    dep_doc = yaml.load(k8s_dep_path.read_text(encoding="utf-8"))
    assert dep_doc["metadata"]["namespace"] == "staging"
    assert dep_doc["spec"]["replicas"] == 3
    dep_container = dep_doc["spec"]["template"]["spec"]["containers"][0]
    assert dep_container["resources"]["requests"] == {"cpu": "150m", "memory": "320Mi"}
    assert dep_container["livenessProbe"]["httpGet"]["path"] == "/healthz"

    cm_doc = yaml.load(k8s_cm_path.read_text(encoding="utf-8"))
    assert cm_doc["metadata"]["namespace"] == "staging"
    assert cm_doc["data"] == {"APP_MODE": "staging"}

    hpa_doc = yaml.load(k8s_hpa_path.read_text(encoding="utf-8"))
    assert hpa_doc["kind"] == "HorizontalPodAutoscaler"
    assert hpa_doc["metadata"]["namespace"] == "staging"
    assert hpa_doc["spec"]["minReplicas"] == 2
    assert hpa_doc["spec"]["maxReplicas"] == 8
    assert hpa_doc["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] == 75

    # 2c. hx check exits 0 with Zero Drift Detected
    check_res = runner.invoke(app, ["check", "--path", str(app_repo)])
    assert check_res.exit_code == 0, check_res.stdout
    assert "Zero Drift Detected" in check_res.stdout

    # 2d. Customize k8s/hpa.yaml on disk and re-run hx generate --yes -> SmartMerger preserves threshold without duplicating cpu metric
    k8s_hpa_path.write_text(
        k8s_hpa_path.read_text(encoding="utf-8").replace("averageUtilization: 75", "averageUtilization: 60"),
        encoding="utf-8",
    )
    regen_res = runner.invoke(app, ["generate", "--path", str(app_repo), "--yes"])
    assert regen_res.exit_code == 0, regen_res.stdout
    hpa_remerged = yaml.load(k8s_hpa_path.read_text(encoding="utf-8"))
    assert len(hpa_remerged["spec"]["metrics"]) == 1
    assert hpa_remerged["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] == 60
    recheck_res = runner.invoke(app, ["check", "--path", str(app_repo)])
    assert recheck_res.exit_code == 0, recheck_res.stdout

    # 3. SEC-01 [engine].templates_dir traversal and symlink escape exit cleanly with code 1 and no traceback
    outside_tpl = tmp_path / "outside_evil.j2"
    outside_tpl.write_text("apiVersion: v1\nkind: Service\n", encoding="utf-8")
    symlink_tpl = local_k8s_tpl_dir / "service.yaml.j2"
    symlink_tpl.unlink()
    symlink_tpl.symlink_to(outside_tpl)
    for cmd_args in (
        ["generate", "--path", str(app_repo), "--yes"],
        ["diff", "--path", str(app_repo)],
        ["check", "--path", str(app_repo)],
    ):
        err_res = runner.invoke(app, cmd_args)
        assert err_res.exit_code == 1
        assert isinstance(err_res.exception, SystemExit)
        assert "Traceback" not in err_res.stdout
        assert "Path traversal security violation" in " ".join(err_res.stdout.split())

    symlink_tpl.unlink()
    toml_path.write_text(
        """[engine]
templates_dir = "../outside"

[ci]
include_dependabot = true
include_k8s = true
""",
        encoding="utf-8",
    )
    for cmd_args in (
        ["generate", "--path", str(app_repo), "--yes"],
        ["diff", "--path", str(app_repo)],
        ["check", "--path", str(app_repo)],
    ):
        err_res = runner.invoke(app, cmd_args)
        assert err_res.exit_code == 1
        assert isinstance(err_res.exception, SystemExit)
        assert "Traceback" not in err_res.stdout
        assert "Path traversal security violation" in " ".join(err_res.stdout.split())


def test_cli_interactive_ambiguity_and_non_interactive_flags(tmp_path: Path, monkeypatch):
    import json
    from ruamel.yaml import YAML

    def _create_ambiguous_repo(repo_dir: Path) -> None:
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / ".nvmrc").write_text("20\n", encoding="utf-8")
        (repo_dir / "package.json").write_text(
            json.dumps(
                {
                    "name": "ambiguous-app",
                    "scripts": {"test": "vitest run", "test:e2e": "playwright test"},
                    "dependencies": {"pg": "^8.11.0", "redis": "^4.6.0"},
                    "devDependencies": {"vitest": "^1.5.0", "@playwright/test": "^1.48.0"},
                }
            ),
            encoding="utf-8",
        )
        (repo_dir / "vercel.json").write_text('{"name": "ambig-vercel"}', encoding="utf-8")
        (repo_dir / "firebase.json").write_text('{"hosting": {"public": "dist"}}', encoding="utf-8")
        (repo_dir / ".firebaserc").write_text('{"projects": {"default": "ambig-fb"}}', encoding="utf-8")
        (repo_dir / "Dockerfile").write_text("FROM node:20-alpine\nEXPOSE 3000\n", encoding="utf-8")

    # 1a. Interactive prompt hooks resolved via monkeypatch in CliRunner (filtering services, targets, E2E split, and k8s)
    interactive_repo = tmp_path / "interactive_repo"
    _create_ambiguous_repo(interactive_repo)

    called_prompts: list[str] = []

    def mock_e2e_split(unit_runners, e2e_runners, *, non_interactive=False):
        called_prompts.append("e2e")
        assert unit_runners == ["vitest"]
        assert e2e_runners == ["playwright"]
        assert non_interactive is False
        return False  # Choose combined mode

    def mock_targets(targets, *, non_interactive=False):
        called_prompts.append("targets")
        assert non_interactive is False
        return [t for t in targets if t.platform == "vercel"]  # Deselect firebase

    def mock_services(services, *, non_interactive=False):
        called_prompts.append("services")
        assert non_interactive is False
        return [s for s in services if s.name == "postgres"]  # Exclude redis

    def mock_k8s(*, default=True, non_interactive=False):
        called_prompts.append("k8s")
        assert non_interactive is False
        return False  # Skip k8s manifests

    monkeypatch.setattr("heurix.cli.prompt_e2e_split", mock_e2e_split)
    monkeypatch.setattr("heurix.cli.prompt_deployment_targets", mock_targets)
    monkeypatch.setattr("heurix.cli.prompt_backing_services", mock_services)
    monkeypatch.setattr("heurix.cli.prompt_k8s_generation", mock_k8s)

    res = runner.invoke(app, ["generate", "--path", str(interactive_repo)])
    assert res.exit_code == 0, res.stdout
    assert called_prompts == ["e2e", "targets", "services", "k8s"]

    yaml = YAML(typ="safe")
    ci_text = (interactive_repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ci_doc = yaml.load(ci_text)
    assert "test-e2e" not in ci_doc["jobs"]
    assert "deploy_vercel" in ci_doc["jobs"]
    assert "deploy_firebase" not in ci_doc["jobs"]
    assert "postgres" in ci_doc["jobs"]["test"]["services"]
    assert "redis" not in ci_doc["jobs"]["test"]["services"]
    assert "FIREBASE_SERVICE_ACCOUNT" not in ci_text
    assert any(
        s.get("name") == "Run E2E tests (playwright)"
        for s in ci_doc["jobs"]["test"]["steps"]
    )
    assert not (interactive_repo / "k8s").exists()

    # 1b. Interactive choices consistent with codebase services pass hx check with zero drift
    (interactive_repo / ".heurix.toml").write_text(
        '[services]\nexclude = ["redis"]\n',
        encoding="utf-8",
    )
    # Policy-explicit services & --no-k8s skip services & k8s prompts even in interactive mode
    called_prompts.clear()
    explicit_res = runner.invoke(app, ["generate", "--path", str(interactive_repo), "--no-k8s", "--yes"])
    assert explicit_res.exit_code == 0, explicit_res.stdout
    check_interactive = runner.invoke(app, ["check", "--path", str(interactive_repo)])
    assert check_interactive.exit_code == 0, check_interactive.stdout
    assert "Zero Drift Detected" in check_interactive.stdout

    # Verify policy-explicit suppression without --yes skips services & k8s prompts
    monkeypatch.setattr(
        "heurix.cli.prompt_conflict_resolution",
        lambda rel_path, non_interactive=False: "apply",
    )
    monkeypatch.setattr(
        "heurix.cli.prompt_backing_services",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("services prompt should be skipped when policy excludes services")),
    )
    monkeypatch.setattr(
        "heurix.cli.prompt_k8s_generation",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("k8s prompt should be skipped when --no-k8s is passed")),
    )
    policy_res = runner.invoke(app, ["generate", "--path", str(interactive_repo), "--no-k8s"])
    assert policy_res.exit_code == 0, policy_res.stdout
    assert called_prompts == ["e2e", "targets"]
    check_after_interactive = runner.invoke(app, ["check", "--path", str(interactive_repo)])
    assert check_after_interactive.exit_code == 0, check_after_interactive.stdout

    # 2. --non-interactive skips all prompts and uses deterministic defaults
    headless_repo = tmp_path / "headless_repo"
    _create_ambiguous_repo(headless_repo)

    def _forbid_prompt(*args, **kwargs):
        raise AssertionError("Interactive prompt should not be called when --non-interactive is set")

    monkeypatch.setattr("heurix.cli.prompt_e2e_split", _forbid_prompt)
    monkeypatch.setattr("heurix.cli.prompt_deployment_targets", _forbid_prompt)
    monkeypatch.setattr("heurix.cli.prompt_backing_services", _forbid_prompt)
    monkeypatch.setattr("heurix.cli.prompt_k8s_generation", _forbid_prompt)
    monkeypatch.setattr("heurix.cli.prompt_conflict_resolution", _forbid_prompt)

    headless_res = runner.invoke(app, ["generate", "--path", str(headless_repo), "--non-interactive"])
    assert headless_res.exit_code == 0, headless_res.stdout

    headless_doc = yaml.load(
        (headless_repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    assert "test-e2e" in headless_doc["jobs"]
    assert "deploy_vercel" in headless_doc["jobs"]
    assert "deploy_firebase" in headless_doc["jobs"]
    assert "postgres" in headless_doc["jobs"]["test"]["services"]
    assert "redis" in headless_doc["jobs"]["test"]["services"]
    assert (headless_repo / "k8s" / "deployment.yaml").exists()

    check_headless = runner.invoke(app, ["check", "--path", str(headless_repo)])
    assert check_headless.exit_code == 0, check_headless.stdout
    assert "Zero Drift Detected" in check_headless.stdout


def test_cli_side_by_side_and_auto_diff_modes(tmp_path: Path):
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    ci_file = ci_dir / "ci.yml"
    ci_file.write_text("name: Old CI\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n", encoding="utf-8")
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    # 1. hx diff --side-by-side renders Rich.Table side-by-side preview
    sbs_res = runner.invoke(
        app,
        ["diff", "--path", str(tmp_path), "--side-by-side"],
        env={"COLUMNS": "140", "NO_COLOR": "1"},
    )
    assert sbs_res.exit_code == 0, sbs_res.stdout
    assert "(side-by-side)" in sbs_res.stdout
    assert "Current" in sbs_res.stdout
    assert "Synthesized" in sbs_res.stdout
    assert "│" in sbs_res.stdout

    # 2. hx diff --diff-style auto adapts to COLUMNS >= 120 vs < 120
    auto_wide = runner.invoke(
        app,
        ["diff", "--path", str(tmp_path), "--diff-style", "auto"],
        env={"COLUMNS": "140", "NO_COLOR": "1"},
    )
    assert auto_wide.exit_code == 0, auto_wide.stdout
    assert "(side-by-side)" in auto_wide.stdout
    assert "│" in auto_wide.stdout

    auto_narrow = runner.invoke(
        app,
        ["diff", "--path", str(tmp_path), "--diff-style", "auto"],
        env={"COLUMNS": "80", "NO_COLOR": "1"},
    )
    assert auto_narrow.exit_code == 0, auto_narrow.stdout
    assert "(side-by-side)" not in auto_narrow.stdout
    assert "Diff Preview:" in auto_narrow.stdout
    assert "@@" in auto_narrow.stdout

    # 3. hx generate --diff --side-by-side --yes writes updates after showing side-by-side diff
    gen_sbs = runner.invoke(
        app,
        ["generate", "--path", str(tmp_path), "--diff", "--side-by-side", "--yes"],
        env={"COLUMNS": "140", "NO_COLOR": "1"},
    )
    assert gen_sbs.exit_code == 0, gen_sbs.stdout
    assert "(side-by-side)" in gen_sbs.stdout
    assert "actions/setup-python@v5" in ci_file.read_text(encoding="utf-8")

    # 4. Invalid --diff-style exits cleanly with code 1 and no traceback
    for bad_cmd in (
        ["generate", "--path", str(tmp_path), "--diff-style", "bogus", "--yes"],
        ["diff", "--path", str(tmp_path), "--diff-style", "bogus"],
    ):
        bad_res = runner.invoke(app, bad_cmd)
        assert bad_res.exit_code == 1
        assert "Traceback" not in bad_res.stdout
        assert "Unsupported diff style" in " ".join(bad_res.stdout.split())


def test_cli_partial_validation_optional_k8s_and_strict(tmp_path: Path, monkeypatch):
    valid_ci = (
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
    )
    valid_dependabot = (
        "version: 2\n"
        "updates:\n"
        "  - package-ecosystem: pip\n"
        "    directory: /\n"
        "    schedule:\n"
        "      interval: weekly\n"
    )
    valid_k8s_svc = (
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: demo\n"
    )
    broken_k8s_dep = "apiVersion: apps/v1\nkind: Deployment\n"  # missing required metadata
    broken_ci = "name: CI\njobs:\n  test:\n    runs-on: ubuntu-latest\n"  # missing required steps

    # 1. Optional k8s failure (strict=False): warns in yellow panel, excludes k8s file, writes valid CI files (exit 0)
    partial_repo = tmp_path / "partial_repo"
    partial_repo.mkdir()
    (partial_repo / ".python-version").write_text("3.12\n", encoding="utf-8")
    (partial_repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            ".github/workflows/ci.yml": valid_ci,
            ".github/dependabot.yml": valid_dependabot,
            "k8s/deployment.yaml": broken_k8s_dep,
        },
    )
    partial_res = runner.invoke(app, ["generate", "--path", str(partial_repo), "--yes"])
    assert partial_res.exit_code == 0, partial_res.stdout
    normalized_partial = " ".join(partial_res.stdout.split())
    assert "Optional Manifest Warnings (Excluded)" in normalized_partial
    assert "k8s/deployment.yaml" in normalized_partial
    assert "--strict" in normalized_partial
    assert (partial_repo / ".github" / "workflows" / "ci.yml").exists()
    assert (partial_repo / ".github" / "dependabot.yml").exists()
    assert not (partial_repo / "k8s" / "deployment.yaml").exists()

    # 2. Only optional k8s file fails (no valid files remain): exits 0 cleanly with warning
    only_opt_repo = tmp_path / "only_opt_repo"
    only_opt_repo.mkdir()
    (only_opt_repo / ".python-version").write_text("3.12\n", encoding="utf-8")
    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            "k8s/deployment.yaml": broken_k8s_dep,
        },
    )
    only_opt_res = runner.invoke(app, ["generate", "--path", str(only_opt_repo), "--yes"])
    assert only_opt_res.exit_code == 0, only_opt_res.stdout
    assert not (only_opt_repo / "k8s" / "deployment.yaml").exists()

    # 3. --strict aborts all writes on optional k8s failure (exit 1, 0 files written)
    strict_repo = tmp_path / "strict_repo"
    strict_repo.mkdir()
    (strict_repo / ".python-version").write_text("3.12\n", encoding="utf-8")
    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            ".github/workflows/ci.yml": valid_ci,
            "k8s/deployment.yaml": broken_k8s_dep,
        },
    )
    strict_res = runner.invoke(app, ["generate", "--path", str(strict_repo), "--yes", "--strict"])
    assert strict_res.exit_code == 1
    assert "Traceback" not in strict_res.stdout
    assert not (strict_repo / ".github" / "workflows" / "ci.yml").exists()
    assert not (strict_repo / "k8s" / "deployment.yaml").exists()

    # 4. Critical CI workflow failure aborts all writes even without --strict (exit 1)
    crit_repo = tmp_path / "crit_repo"
    crit_repo.mkdir()
    (crit_repo / ".python-version").write_text("3.12\n", encoding="utf-8")
    monkeypatch.setattr(
        "heurix.cli.synthesize_all",
        lambda context, include_k8s=True, include_dependabot=True: {
            ".github/workflows/ci.yml": broken_ci,
            "k8s/service.yaml": valid_k8s_svc,
        },
    )
    crit_res = runner.invoke(app, ["generate", "--path", str(crit_repo), "--yes"])
    assert crit_res.exit_code == 1
    assert "Traceback" not in crit_res.stdout
    assert not (crit_repo / ".github" / "workflows" / "ci.yml").exists()
    assert not (crit_repo / "k8s" / "service.yaml").exists()


def test_cli_init_pre_commit_hooks_lifecycle(tmp_path: Path, monkeypatch):
    import os
    import stat
    from heurix.core.hooks import HOOK_END_MARKER, HOOK_START_MARKER

    # 1. Fresh git repo with --hooks creates .heurix.toml + executable pre-commit hook
    fresh_repo = tmp_path / "fresh_git_repo"
    (fresh_repo / ".git").mkdir(parents=True)
    res_fresh = runner.invoke(app, ["init", "--path", str(fresh_repo), "--hooks"])
    assert res_fresh.exit_code == 0, res_fresh.stdout
    assert (fresh_repo / ".heurix.toml").exists()
    hook_path = fresh_repo / ".git" / "hooks" / "pre-commit"
    assert hook_path.is_file()
    assert stat.S_IMODE(hook_path.stat().st_mode) == 0o755
    hook_text = hook_path.read_text(encoding="utf-8")
    assert HOOK_START_MARKER in hook_text
    assert HOOK_END_MARKER in hook_text
    assert "hx check --path ." in hook_text

    # 2. Re-running hx init --hooks on existing .heurix.toml + custom hook preserves both idempotently
    existing_repo = tmp_path / "existing_repo"
    (existing_repo / ".git" / "hooks").mkdir(parents=True)
    custom_toml = "# custom user policy\n[engine]\nrunner = 'ubuntu-24.04'\n"
    (existing_repo / ".heurix.toml").write_text(custom_toml, encoding="utf-8")
    existing_hook = existing_repo / ".git" / "hooks" / "pre-commit"
    existing_hook.write_text(
        "#!/usr/bin/env sh\n"
        "echo 'user-before'\n\n"
        f"{HOOK_START_MARKER}\n"
        "echo 'stale-block'\n"
        f"{HOOK_END_MARKER}\n\n"
        "echo 'user-after'\n",
        encoding="utf-8",
    )
    existing_hook.chmod(0o644)

    res_existing = runner.invoke(app, ["init", "--path", str(existing_repo), "--hooks"])
    assert res_existing.exit_code == 0, res_existing.stdout
    assert ".heurix.toml already exists." in res_existing.stdout
    assert (existing_repo / ".heurix.toml").read_text(encoding="utf-8") == custom_toml
    assert stat.S_IMODE(existing_hook.stat().st_mode) == 0o755
    updated_hook_text = existing_hook.read_text(encoding="utf-8")
    assert "echo 'user-before'" in updated_hook_text
    assert "echo 'user-after'" in updated_hook_text
    assert "stale-block" not in updated_hook_text
    assert HOOK_START_MARKER in updated_hook_text

    res_repeat = runner.invoke(app, ["init", "--path", str(existing_repo), "--hooks"])
    assert res_repeat.exit_code == 0, res_repeat.stdout
    assert existing_hook.read_text(encoding="utf-8") == updated_hook_text

    # 3. --no-hooks skips hook installation and prompt
    no_hooks_repo = tmp_path / "no_hooks_repo"
    (no_hooks_repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "heurix.cli.prompt_install_hooks",
        lambda **kw: (_ for _ in ()).throw(AssertionError("prompt_install_hooks must not run with --no-hooks")),
    )
    res_no_hooks = runner.invoke(app, ["init", "--path", str(no_hooks_repo), "--no-hooks"])
    assert res_no_hooks.exit_code == 0, res_no_hooks.stdout
    assert (no_hooks_repo / ".heurix.toml").exists()
    assert not (no_hooks_repo / ".git" / "hooks" / "pre-commit").exists()

    # 4. Interactive confirmation via monkeypatched prompt_install_hooks vs --yes / --non-interactive
    prompt_repo = tmp_path / "prompt_repo"
    (prompt_repo / ".git").mkdir(parents=True)
    monkeypatch.setattr("heurix.cli.prompt_install_hooks", lambda non_interactive=False: True)
    res_prompt = runner.invoke(app, ["init", "--path", str(prompt_repo)])
    assert res_prompt.exit_code == 0, res_prompt.stdout
    assert (prompt_repo / ".git" / "hooks" / "pre-commit").is_file()

    headless_repo = tmp_path / "headless_init_repo"
    (headless_repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        "heurix.cli.prompt_install_hooks",
        lambda **kw: (_ for _ in ()).throw(AssertionError("prompt_install_hooks must not run with --non-interactive")),
    )
    res_headless = runner.invoke(app, ["init", "--path", str(headless_repo), "--non-interactive"])
    assert res_headless.exit_code == 0, res_headless.stdout
    assert not (headless_repo / ".git" / "hooks" / "pre-commit").exists()

    # 5. --hooks without .git warns cleanly without crashing
    no_git_repo = tmp_path / "no_git_repo"
    no_git_repo.mkdir()
    res_no_git = runner.invoke(app, ["init", "--path", str(no_git_repo), "--hooks"])
    assert res_no_git.exit_code == 0, res_no_git.stdout
    assert "No .git directory" in " ".join(res_no_git.stdout.split())
    assert "Traceback" not in res_no_git.stdout

    # 6. SEC-01 symlinked .git/hooks traversal blocked with exit 1 and no traceback
    outside_dir = tmp_path / "outside_hooks"
    outside_dir.mkdir()
    escape_repo = tmp_path / "escape_hooks_repo"
    (escape_repo / ".git").mkdir(parents=True)
    (escape_repo / ".git" / "hooks").symlink_to(outside_dir)

    res_escape = runner.invoke(app, ["init", "--path", str(escape_repo), "--hooks"])
    assert res_escape.exit_code == 1
    assert "Traceback" not in res_escape.stdout
    assert "Path traversal security violation" in " ".join(res_escape.stdout.split())
    assert not (outside_dir / "pre-commit").exists()

    # 7. Read-only .git/hooks / PermissionError handled cleanly without traceback
    ro_repo = tmp_path / "ro_hooks_repo"
    ro_hooks_dir = ro_repo / ".git" / "hooks"
    ro_hooks_dir.mkdir(parents=True)
    if os.geteuid() != 0:
        ro_hooks_dir.chmod(0o555)
        try:
            res_ro = runner.invoke(app, ["init", "--path", str(ro_repo), "--hooks"])
            assert res_ro.exit_code == 1
            assert "Traceback" not in res_ro.stdout
            assert "Pre-Commit Hook Error" in " ".join(res_ro.stdout.split())
        finally:
            ro_hooks_dir.chmod(0o755)

    # Deterministic OSError simulation via monkeypatched install_pre_commit_hook / write_text
    ro_perm_repo = tmp_path / "ro_perm_repo"
    (ro_perm_repo / ".git" / "hooks").mkdir(parents=True)
    orig_write_text = Path.write_text

    def _deny_hook_write(self: Path, data: str, *args, **kwargs):
        if self.name == "pre-commit":
            raise PermissionError("Permission denied: read-only .git/hooks")
        return orig_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _deny_hook_write)
    res_perm_explicit = runner.invoke(app, ["init", "--path", str(ro_perm_repo), "--hooks"])
    assert res_perm_explicit.exit_code == 1
    assert "Traceback" not in res_perm_explicit.stdout
    assert "Permission denied" in " ".join(res_perm_explicit.stdout.split())

    # Optional interactive confirmation failure warns cleanly without traceback
    monkeypatch.setattr("heurix.cli.prompt_install_hooks", lambda non_interactive=False: True)
    res_perm_opt = runner.invoke(app, ["init", "--path", str(ro_perm_repo)])
    assert res_perm_opt.exit_code == 0, res_perm_opt.stdout
    assert "Traceback" not in res_perm_opt.stdout
    assert "Pre-Commit Hook Warning" in " ".join(res_perm_opt.stdout.split())


def test_cli_generate_empty_directory_refusal(tmp_path: Path):
    runner = CliRunner()
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()

    # 1. By default, hx generate refuses to write into empty directory
    res = runner.invoke(app, ["generate", "--path", str(empty_dir), "--yes"])
    assert res.exit_code == 0
    assert "Empty Repository" in res.stdout
    assert "Refusing to generate empty workflows" in res.stdout
    assert not (empty_dir / ".github").exists()

    # 2. Overriding with --allow-empty bypasses refusal
    res_override = runner.invoke(app, ["generate", "--path", str(empty_dir), "--yes", "--allow-empty"])
    assert res_override.exit_code == 0
    assert "Refusing to generate empty workflows" not in res_override.stdout


