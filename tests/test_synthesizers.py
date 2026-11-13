"""
Tests for YAML Synthesizers.
"""

from __future__ import annotations

from pathlib import Path

from heurix.core.context import ContainerContext, DeploymentTarget, LanguageContext, ProjectContext, ServiceRequirement
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
                test_cmd="uv run pytest",
                lint_cmd="uv run ruff check .",
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
        test_secrets=["DATABASE_URL"],
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
    assert "uv run ruff check ." in content
    assert "uv run pytest" in content
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

    # Verify modernized ingress spec
    ing = res["k8s/ingress.yaml"]
    assert "ingressClassName: nginx" in ing
    assert "kubernetes.io/ingress.class" not in ing


def test_kubernetes_synthesizer_streamlit_and_configmap():
    context = ProjectContext(
        repo_name="my_dashboard",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.11",
                version_source="pyproject.toml",
                package_manager="poetry",
                install_cmd="poetry install",
                framework="Streamlit",
            )
        ],
        containers=[ContainerContext(dockerfile_path="Dockerfile")],
        env_vars={"STREAMLIT_SERVER_HEADLESS": "true", "APP_ENV": "production"},
        required_secrets=["API_KEY"],
    )

    syn = KubernetesSynthesizer()
    res = syn.synthesize(context)

    assert "k8s/deployment.yaml" in res
    assert "k8s/service.yaml" in res
    assert "k8s/ingress.yaml" in res
    assert "k8s/configmap.yaml" in res

    dep = res["k8s/deployment.yaml"]
    assert "containerPort: 8501" in dep
    assert "/_stcore/health" in dep
    assert "configMapRef:" in dep
    assert "my-dashboard-config" in dep
    assert "secretRef:" in dep
    assert "my-dashboard-secrets" in dep
    assert "optional: true" in dep or "optional: True" in dep

    svc = res["k8s/service.yaml"]
    assert "targetPort: 8501" in svc

    cm = res["k8s/configmap.yaml"]
    assert "STREAMLIT_SERVER_HEADLESS: 'true'" in cm or 'STREAMLIT_SERVER_HEADLESS: "true"' in cm or "STREAMLIT_SERVER_HEADLESS: true" in cm
    assert "APP_ENV: production" in cm

    ing = res["k8s/ingress.yaml"]
    assert "ingressClassName: nginx" in ing


def test_github_actions_synthesizer_cloud_targets():
    context = ProjectContext(
        repo_name="my-fullstack-app",
        repo_root="/app",
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source="package.json",
                package_manager="pnpm",
                install_cmd="pnpm i",
                test_cmd="pnpm test",
            )
        ],
        deployment_targets=[
            DeploymentTarget(
                platform="vercel",
                config_file="vercel.json",
                project_id="my-fullstack-app",
                features=["hosting", "serverless"],
                deploy_cmd="vercel --prod",
                required_secrets=["VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"],
            ),
            DeploymentTarget(
                platform="firebase",
                config_file="firebase.json",
                project_id="my-firebase-app",
                features=["hosting"],
                deploy_cmd="firebase deploy --only hosting",
                required_secrets=["FIREBASE_SERVICE_ACCOUNT"],
            ),
        ],
    )

    syn = GitHubActionsSynthesizer()
    res = syn.synthesize(context)
    ci_content = res[".github/workflows/ci.yml"]

    # Vercel deployment job synthesized
    assert "deploy_vercel:" in ci_content
    assert "amondnet/vercel-action@v25" in ci_content
    assert "${{ secrets.VERCEL_TOKEN }}" in ci_content

    # Firebase deployment job synthesized
    assert "deploy_firebase:" in ci_content
    assert "FirebaseExtended/action-hosting-deploy@v0" in ci_content
    assert "${{ secrets.FIREBASE_SERVICE_ACCOUNT }}" in ci_content
    assert "my-firebase-app" in ci_content


def test_kubernetes_synthesizer_kind_cluster():
    context = ProjectContext(
        repo_name="api_svc",
        repo_root="/app",
        containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
    )

    syn = KubernetesSynthesizer()
    res = syn.synthesize(context)

    assert "k8s/kind-config.yaml" in res
    kind_yaml = res["k8s/kind-config.yaml"]
    assert "kind: Cluster" in kind_yaml
    assert "apiVersion: kind.x-k8s.io/v1alpha4" in kind_yaml
    assert "ingress-ready=true" in kind_yaml
    assert "hostPort: 80" in kind_yaml
    assert "hostPort: 443" in kind_yaml


def test_secret_scoping_isolates_deployment_secrets_from_test_job():
    from ruamel.yaml import YAML

    context = ProjectContext(
        repo_name="demo-secure-app",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="uv",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
            )
        ],
        test_secrets=["TEST_DB_PASSWORD", "TEST_API_KEY"],
        deployment_secrets=[
            "VERCEL_TOKEN",
            "VERCEL_ORG_ID",
            "VERCEL_PROJECT_ID",
            "FIREBASE_SERVICE_ACCOUNT",
            "AWS_ACCESS_KEY_ID",
        ],
        required_secrets=[
            "TEST_DB_PASSWORD",
            "TEST_API_KEY",
            "VERCEL_TOKEN",
            "VERCEL_ORG_ID",
            "VERCEL_PROJECT_ID",
            "FIREBASE_SERVICE_ACCOUNT",
            "AWS_ACCESS_KEY_ID",
            "UNSCOPED_LEGACY_SECRET",
        ],
        deployment_targets=[
            DeploymentTarget(
                platform="vercel",
                config_file="vercel.json",
                project_id="demo-secure-app",
                required_secrets=["VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"],
            ),
            DeploymentTarget(
                platform="firebase",
                config_file="firebase.json",
                project_id="demo-fb",
                required_secrets=["FIREBASE_SERVICE_ACCOUNT"],
            ),
        ],
    )

    syn = GitHubActionsSynthesizer()
    res = syn.synthesize(context)
    ci_yaml = res[".github/workflows/ci.yml"]
    doc = YAML(typ="safe").load(ci_yaml)

    test_job = doc["jobs"]["test"]
    test_step = next(s for s in test_job["steps"] if s.get("run") == "uv run pytest")
    test_env = test_step.get("env", {})

    assert test_env["TEST_DB_PASSWORD"] == "${{ secrets.TEST_DB_PASSWORD }}"
    assert test_env["TEST_API_KEY"] == "${{ secrets.TEST_API_KEY }}"

    test_job_serialized = str(test_job)
    for forbidden in (
        "VERCEL_TOKEN",
        "VERCEL_ORG_ID",
        "VERCEL_PROJECT_ID",
        "FIREBASE_SERVICE_ACCOUNT",
        "AWS_ACCESS_KEY_ID",
        "UNSCOPED_LEGACY_SECRET",
    ):
        assert forbidden not in test_env
        assert forbidden not in test_job_serialized

    deploy_vercel = doc["jobs"]["deploy_vercel"]
    assert deploy_vercel["needs"] == "test"
    assert deploy_vercel["if"] == "github.ref == 'refs/heads/main' && github.event_name == 'push'"
    vercel_with = deploy_vercel["steps"][1]["with"]
    assert vercel_with["vercel-token"] == "${{ secrets.VERCEL_TOKEN }}"
    assert vercel_with["vercel-org-id"] == "${{ secrets.VERCEL_ORG_ID }}"
    assert vercel_with["vercel-project-id"] == "${{ secrets.VERCEL_PROJECT_ID }}"

    deploy_firebase = doc["jobs"]["deploy_firebase"]
    assert deploy_firebase["needs"] == "test"
    assert deploy_firebase["if"] == "github.ref == 'refs/heads/main' && github.event_name == 'push'"
    fb_with = deploy_firebase["steps"][1]["with"]
    assert fb_with["firebaseServiceAccount"] == "${{ secrets.FIREBASE_SERVICE_ACCOUNT }}"


def test_secret_scoping_excludes_deployment_secrets_even_if_duplicated():
    from ruamel.yaml import YAML

    context = ProjectContext(
        repo_name="dup-sec",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
            )
        ],
        test_secrets=["SAFE_TEST_SECRET", "VERCEL_TOKEN"],
        deployment_secrets=["VERCEL_TOKEN"],
    )
    res = GitHubActionsSynthesizer().synthesize(context)
    doc = YAML(typ="safe").load(res[".github/workflows/ci.yml"])
    test_step = next(s for s in doc["jobs"]["test"]["steps"] if s.get("run") == "pytest")
    assert test_step["env"] == {"SAFE_TEST_SECRET": "${{ secrets.SAFE_TEST_SECRET }}"}


def test_configmap_redaction_filters_sensitive_keywords():
    from ruamel.yaml import YAML

    context = ProjectContext(
        repo_name="k8s-sec",
        repo_root="/demo",
        containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
        env_vars={
            "APP_ENV": "production",
            "LOG_LEVEL": "info",
            "PORT": "8000",
            "API_SECRET": "s3cr3t",
            "DB_PASSWORD": "pw",
            "AUTH_TOKEN": "tok",
            "SIGNING_KEY": "key",
            "OAUTH_CLIENT": "oauth",
            "PRIVATE_PEM": "pem",
            "GCP_CREDENTIAL": "cred",
            "TLS_CERT": "cert",
            "DATABASE_URL": "postgres://user:pw@host:5432/db",
            "REDIS_URI": "redis://localhost:6379",
            "SENTRY_DSN": "https://key@sentry.io/1",
            "DB_CONN_STRING": "Server=db;",
            "STRIPE_WEBHOOK": "whsec_123",
            "SESSION_ID": "sess",
            "FIREBASE_SERVICE_ACCOUNT": "{}",
        },
        test_secrets=["DATABASE_URL"],
    )

    res = KubernetesSynthesizer().synthesize(context)
    assert "k8s/configmap.yaml" in res
    cm_yaml = res["k8s/configmap.yaml"]
    cm_doc = YAML(typ="safe").load(cm_yaml)
    data = cm_doc["data"]

    assert data == {"APP_ENV": "production", "LOG_LEVEL": "info", "PORT": "8000"}
    for redacted in (
        "API_SECRET",
        "DB_PASSWORD",
        "AUTH_TOKEN",
        "SIGNING_KEY",
        "OAUTH_CLIENT",
        "PRIVATE_PEM",
        "GCP_CREDENTIAL",
        "TLS_CERT",
        "DATABASE_URL",
        "REDIS_URI",
        "SENTRY_DSN",
        "DB_CONN_STRING",
        "STRIPE_WEBHOOK",
        "SESSION_ID",
        "FIREBASE_SERVICE_ACCOUNT",
    ):
        assert redacted not in data
        assert redacted not in cm_yaml


def test_configmap_redaction_omits_empty_configmap_when_all_vars_sensitive():
    context = ProjectContext(
        repo_name="k8s-only-sec",
        repo_root="/demo",
        containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
        env_vars={
            "DATABASE_URL": "postgres://user:pw@host:5432/db",
            "API_SECRET": "s3cr3t",
        },
    )

    res = KubernetesSynthesizer().synthesize(context)
    assert "k8s/configmap.yaml" not in res
    assert "configMapRef" not in res["k8s/deployment.yaml"]


def test_go_linter_action_integration():
    from ruamel.yaml import YAML
    from heurix.core.validator import PreflightValidator

    context = ProjectContext(
        repo_name="go-service",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="go",
                runtime_version="1.22",
                version_source="go.mod",
                package_manager="gomod",
                install_cmd="go mod download",
                build_cmd="go build -v ./...",
                test_cmd="go test -v -race -cover ./...",
                lint_cmd="golangci-lint run",
            )
        ],
    )

    res = GitHubActionsSynthesizer().synthesize(context)
    ci_yaml = res[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", ci_yaml)
    assert is_valid, f"Validation failed: {errors}"

    doc = YAML(typ="safe").load(ci_yaml)
    steps = doc["jobs"]["test"]["steps"]
    lint_steps = [s for s in steps if s.get("uses") == "golangci/golangci-lint-action@v4"]
    assert len(lint_steps) == 1
    assert lint_steps[0]["with"] == {"version": "v1.57"}
    assert not any("golangci-lint run" in str(s.get("run", "")) for s in steps)

    # Without lint_cmd, golangci-lint-action must not be injected
    context.languages[0].lint_cmd = None
    res_no_lint = GitHubActionsSynthesizer().synthesize(context)
    doc_no_lint = YAML(typ="safe").load(res_no_lint[".github/workflows/ci.yml"])
    assert not any(
        "golangci-lint-action" in str(s.get("uses", ""))
        for s in doc_no_lint["jobs"]["test"]["steps"]
    )


def test_cross_platform_cpp_runner_adaptation():
    from ruamel.yaml import YAML

    def _cpp_context(runner: str, lint_cmd: str | None = None) -> ProjectContext:
        return ProjectContext(
            repo_name="cpp-engine",
            repo_root="/demo",
            runner=runner,
            languages=[
                LanguageContext(
                    language="cpp",
                    runtime_version="c++20",
                    version_source="CMakeLists.txt",
                    package_manager="cmake",
                    install_cmd="cmake -B build -S .",
                    build_cmd="cmake -B build -S . && cmake --build build",
                    test_cmd="ctest --test-dir build --output-on-failure",
                    lint_cmd=lint_cmd,
                )
            ],
        )

    syn = GitHubActionsSynthesizer()

    # Ubuntu runner -> apt-get
    ubuntu_doc = YAML(typ="safe").load(
        syn.synthesize(_cpp_context("ubuntu-latest", lint_cmd="clang-tidy -p build"))[".github/workflows/ci.yml"]
    )
    assert ubuntu_doc["jobs"]["test"]["runs-on"] == "ubuntu-latest"
    ubuntu_runs = [s.get("run", "") for s in ubuntu_doc["jobs"]["test"]["steps"]]
    assert any(
        "sudo apt-get update && sudo apt-get install -y cmake ninja-build build-essential clang-tidy" in r
        for r in ubuntu_runs
    )

    # macOS runner -> brew
    mac_doc = YAML(typ="safe").load(
        syn.synthesize(_cpp_context("macos-latest"))[".github/workflows/ci.yml"]
    )
    assert mac_doc["jobs"]["test"]["runs-on"] == "macos-latest"
    mac_runs = [s.get("run", "") for s in mac_doc["jobs"]["test"]["steps"]]
    assert "brew install cmake ninja" in mac_runs
    assert not any("apt-get" in r for r in mac_runs)

    # Windows runner -> choco
    win_doc = YAML(typ="safe").load(
        syn.synthesize(_cpp_context("windows-latest"))[".github/workflows/ci.yml"]
    )
    assert win_doc["jobs"]["test"]["runs-on"] == "windows-latest"
    win_runs = [s.get("run", "") for s in win_doc["jobs"]["test"]["steps"]]
    assert "choco install cmake ninja" in win_runs
    assert not any("apt-get" in r for r in win_runs)


def test_branch_target_dynamic_conditionals():
    from ruamel.yaml import YAML

    def _deploy_ctx(policy_config: dict) -> ProjectContext:
        return ProjectContext(
            repo_name="branch-app",
            repo_root="/demo",
            languages=[
                LanguageContext(
                    language="node",
                    runtime_version="20.x",
                    version_source="package.json",
                    package_manager="npm",
                    install_cmd="npm ci",
                    test_cmd="npm test",
                )
            ],
            deployment_targets=[
                DeploymentTarget(
                    platform="vercel",
                    config_file="vercel.json",
                    project_id="branch-app",
                    required_secrets=["VERCEL_TOKEN"],
                ),
                DeploymentTarget(
                    platform="firebase",
                    config_file="firebase.json",
                    project_id="branch-fb",
                    required_secrets=["FIREBASE_SERVICE_ACCOUNT"],
                ),
            ],
            policy_config=policy_config,
        )

    syn = GitHubActionsSynthesizer()

    # Default branch -> main
    doc_default = YAML(typ="safe").load(syn.synthesize(_deploy_ctx({}))[".github/workflows/ci.yml"])
    assert doc_default["jobs"]["deploy_vercel"]["if"] == "github.ref == 'refs/heads/main' && github.event_name == 'push'"
    assert doc_default["jobs"]["deploy_firebase"]["if"] == "github.ref == 'refs/heads/main' && github.event_name == 'push'"

    # Configured master branch
    doc_master = YAML(typ="safe").load(
        syn.synthesize(_deploy_ctx({"ci": {"default_branch": "master"}}))[".github/workflows/ci.yml"]
    )
    assert doc_master["jobs"]["deploy_vercel"]["if"] == "github.ref == 'refs/heads/master' && github.event_name == 'push'"
    assert doc_master["jobs"]["deploy_firebase"]["if"] == "github.ref == 'refs/heads/master' && github.event_name == 'push'"

    # Custom branch -> develop (both deployment if and workflow triggers)
    doc_develop = YAML(typ="safe").load(
        syn.synthesize(_deploy_ctx({"ci": {"default_branch": "develop"}}))[".github/workflows/ci.yml"]
    )
    assert doc_develop["jobs"]["deploy_vercel"]["if"] == "github.ref == 'refs/heads/develop' && github.event_name == 'push'"
    assert doc_develop["jobs"]["deploy_firebase"]["if"] == "github.ref == 'refs/heads/develop' && github.event_name == 'push'"
    assert "develop" in doc_develop["on"]["push"]["branches"]
    assert "develop" in doc_develop["on"]["pull_request"]["branches"]


def test_action_pinning_and_optional_sha_pinning():
    import re
    from ruamel.yaml import YAML
    from heurix.core.validator import PreflightValidator

    checkout_sha = "b4ffde65f46336ab88eb53be808477a3936bae11"
    lint_sha = "3b7c8f1a2d9e0c4b5a6f7e8d9c0b1a2f3e4d5c6b"

    context = ProjectContext(
        repo_name="sha-pinned-go",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="go",
                runtime_version="1.22",
                version_source="go.mod",
                package_manager="gomod",
                install_cmd="go mod download",
                test_cmd="go test ./...",
                lint_cmd="golangci-lint run",
            )
        ],
        policy_config={
            "ci": {
                "action_shas": {
                    "actions/checkout": checkout_sha,
                    "golangci/golangci-lint-action": lint_sha,
                }
            }
        },
    )

    ci_yaml = GitHubActionsSynthesizer().synthesize(context)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", ci_yaml)
    assert is_valid, f"Validation failed: {errors}"

    assert re.search(rf"uses: actions/checkout@{checkout_sha}\s+# v4", ci_yaml)
    assert re.search(rf"uses: golangci/golangci-lint-action@{lint_sha}\s+# v4", ci_yaml)
    assert "actions/setup-go@v5" in ci_yaml

    doc = YAML(typ="safe").load(ci_yaml)
    uses_vals = [s["uses"] for s in doc["jobs"]["test"]["steps"] if "uses" in s]
    assert f"actions/checkout@{checkout_sha}" in uses_vals
    assert f"golangci/golangci-lint-action@{lint_sha}" in uses_vals


def test_multijob_polyglot_monorepo_splitting_and_paths():
    import re
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator
    from heurix.synthesizers.github_actions import sanitize_job_id

    # Verify sanitize_job_id handles invalid chars, leading digits, >100 chars, and collisions
    used: set[str] = set()
    assert sanitize_job_id("apps/web", used) == "test-apps-web"
    assert sanitize_job_id("apps/web", used) == "test-apps-web-2"
    assert sanitize_job_id("@scope/pkg.name", used) == "test-scope-pkg-name"
    assert sanitize_job_id("123/service", used) == "test-123-service"
    long_id = sanitize_job_id("packages/" + "a" * 120, used)
    assert len(long_id) <= 100
    assert re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", long_id)
    long_dup = sanitize_job_id("packages/" + "a" * 120, used)
    assert len(long_dup) <= 100
    assert long_dup != long_id
    assert re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", long_dup)

    # 1. Polyglot monorepo with Node, Python (uv), Rust, Go, and same-dir Python+Node collision
    context = ProjectContext(
        repo_name="poly-mono",
        repo_root="/mono",
        is_monorepo=True,
        languages=[
            # Virtual workspace coordinator should be skipped when sub-packages exist
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source="package.json",
                package_manager="pnpm",
                install_cmd="pnpm install",
                is_workspace_root=True,
            ),
            # Left as default is_workspace_root=None at root with sub-packages -> also skipped
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="uv",
                install_cmd="uv sync",
                is_workspace_root=None,
            ),
        ],
        monorepo_packages=[
            MonorepoPackage(
                name="@web/frontend",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                runtime_version="20.x",
                install_cmd="pnpm --filter @web/frontend install",
                build_cmd="pnpm build",
                test_cmd="pnpm test",
                cache_dependency_path="pnpm-lock.yaml",
            ),
            MonorepoPackage(
                name="api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
                lint_cmd="uv run ruff check .",
            ),
            MonorepoPackage(
                name="core-rs",
                path="crates/core",
                language="rust",
                package_manager="cargo",
                runtime_version="stable",
                install_cmd=None,
                build_cmd="cargo build --release",
                test_cmd="cargo test",
            ),
            MonorepoPackage(
                name="gateway-go",
                path="services/gateway",
                language="go",
                package_manager="gomod",
                runtime_version="1.22",
                install_cmd=None,  # Guard install_cmd=None
                test_cmd="go test ./...",
                lint_cmd="golangci-lint run",
                cache_dependency_path=None,  # Guard cache-dependency-path=None
            ),
            # Same-dir multi-language collision inside apps/shared
            MonorepoPackage(
                name="shared-py",
                path="apps/shared",
                language="python",
                package_manager="pip",
                runtime_version="3.11",
                install_cmd=None,  # Guard install_cmd=None in pip branch!
                test_cmd="pytest",
                cache_dependency_path="apps/shared/requirements.txt",
            ),
            MonorepoPackage(
                name="shared-js",
                path="apps/shared",
                language="node",
                package_manager="npm",
                runtime_version="20.x",
                install_cmd="npm ci",
                test_cmd="npm test",
                cache_dependency_path="apps/shared/package-lock.json",
            ),
        ],
    )

    ci_yaml = GitHubActionsSynthesizer().synthesize(context)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", ci_yaml)
    assert is_valid, f"Validation failed: {errors}"

    doc = YAML(typ="safe").load(ci_yaml)
    jobs = doc["jobs"]
    assert "test" not in jobs

    expected_jobs = {
        "test-apps-web",
        "test-services-api",
        "test-crates-core",
        "test-services-gateway",
        "test-apps-shared-node",
        "test-apps-shared-python",
    }
    assert set(jobs.keys()) == expected_jobs

    for job_id in jobs:
        assert re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", job_id)

    # Path filters cover sorted sub-package globs (no root package active)
    expected_paths = [
        "apps/shared/**",
        "apps/web/**",
        "crates/core/**",
        "services/api/**",
        "services/gateway/**",
    ]
    assert doc["on"]["push"]["paths"] == expected_paths
    assert doc["on"]["pull_request"]["paths"] == expected_paths

    # Node pnpm sub-package working-directory & root lockfile cache-dependency-path
    assert jobs["test-apps-web"]["defaults"]["run"]["working-directory"] == "apps/web"
    setup_node = next(s for s in jobs["test-apps-web"]["steps"] if "actions/setup-node" in s.get("uses", ""))
    assert setup_node["with"]["cache-dependency-path"] == "pnpm-lock.yaml"

    # Python uv sub-package setup-uv working-directory
    assert jobs["test-services-api"]["defaults"]["run"]["working-directory"] == "services/api"
    setup_uv = next(s for s in jobs["test-services-api"]["steps"] if "astral-sh/setup-uv" in s.get("uses", ""))
    assert setup_uv["with"]["working-directory"] == "services/api"

    # Rust sub-package Swatinem/rust-cache workspaces + prefix-key
    assert jobs["test-crates-core"]["defaults"]["run"]["working-directory"] == "crates/core"
    rust_cache = next(s for s in jobs["test-crates-core"]["steps"] if "Swatinem/rust-cache" in s.get("uses", ""))
    assert rust_cache["with"]["workspaces"] == "crates/core -> target"
    assert rust_cache["with"]["prefix-key"] == "test-crates-core"

    # Go sub-package golangci-lint working-directory + None guards for install_cmd and cache-dependency-path
    assert jobs["test-services-gateway"]["defaults"]["run"]["working-directory"] == "services/gateway"
    setup_go = next(s for s in jobs["test-services-gateway"]["steps"] if "actions/setup-go" in s.get("uses", ""))
    assert "cache-dependency-path" not in setup_go["with"]
    assert not any(s.get("name") == "Download Go dependencies" for s in jobs["test-services-gateway"]["steps"])
    go_lint = next(s for s in jobs["test-services-gateway"]["steps"] if "golangci-lint-action" in s.get("uses", ""))
    assert go_lint["with"]["working-directory"] == "services/gateway"

    # Python pip sub-package with install_cmd=None and cache_dependency_path set
    setup_py = next(s for s in jobs["test-apps-shared-python"]["steps"] if "actions/setup-python" in s.get("uses", ""))
    assert setup_py["with"]["cache-dependency-path"] == "apps/shared/requirements.txt"
    assert not any(s.get("name") == "Install dependencies" for s in jobs["test-apps-shared-python"]["steps"])

    # Hybrid monorepo with active root package falls back to paths: ["**"]
    hybrid_ctx = ProjectContext(
        repo_name="hybrid-mono",
        repo_root="/hybrid",
        is_monorepo=True,
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="pip",
                install_cmd="pip install -e .",
                test_cmd="pytest",
                working_dir=".",
                is_workspace_root=False,
            )
        ],
        monorepo_packages=[
            MonorepoPackage(
                name="web",
                path="apps/web",
                language="node",
                package_manager="npm",
                runtime_version="20.x",
                install_cmd="npm ci",
                test_cmd="npm test",
            )
        ],
    )
    hybrid_doc = YAML(typ="safe").load(GitHubActionsSynthesizer().synthesize(hybrid_ctx)[".github/workflows/ci.yml"])
    assert "test-python" in hybrid_doc["jobs"]
    assert "test-apps-web" in hybrid_doc["jobs"]
    assert "defaults" not in hybrid_doc["jobs"]["test-python"]
    assert hybrid_doc["jobs"]["test-apps-web"]["defaults"]["run"]["working-directory"] == "apps/web"
    assert hybrid_doc["on"]["push"]["paths"] == ["**"]
    assert hybrid_doc["on"]["pull_request"]["paths"] == ["**"]


def test_multijob_scoped_services_secrets_and_deploy_needs():
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator

    context = ProjectContext(
        repo_name="mono-deploy",
        repo_root="/mono",
        is_monorepo=True,
        monorepo_packages=[
            MonorepoPackage(
                name="web",
                path="apps/web",
                language="node",
                package_manager="npm",
                runtime_version="20.x",
                install_cmd="npm ci",
                test_cmd="npm test",
            ),
            MonorepoPackage(
                name="api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
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
                package_path=None,
            ),
        ],
        test_secrets=["API_TEST_KEY", "VERCEL_TOKEN"],
        deployment_secrets=["VERCEL_TOKEN", "FIREBASE_SERVICE_ACCOUNT"],
        deployment_targets=[
            DeploymentTarget(
                platform="vercel",
                config_file="vercel.json",
                project_id="mono-deploy",
                required_secrets=["VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"],
            ),
            DeploymentTarget(
                platform="firebase",
                config_file="firebase.json",
                project_id="mono-fb",
                required_secrets=["FIREBASE_SERVICE_ACCOUNT"],
            ),
        ],
    )

    ci_yaml = GitHubActionsSynthesizer().synthesize(context)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", ci_yaml)
    assert is_valid, f"Validation failed: {errors}"

    doc = YAML(typ="safe").load(ci_yaml)
    jobs = doc["jobs"]

    # postgres is scoped strictly to services/api, while global docker-compose redis attaches to both
    assert "postgres" in jobs["test-services-api"]["services"]
    assert "postgres" not in jobs["test-apps-web"]["services"]
    assert "redis" in jobs["test-services-api"]["services"]
    assert "redis" in jobs["test-apps-web"]["services"]

    # SEC-03 secret isolation across every parallel test job
    for job_id in ("test-apps-web", "test-services-api"):
        test_step = next(s for s in jobs[job_id]["steps"] if s.get("name", "").startswith("Run tests"))
        assert test_step["env"] == {"API_TEST_KEY": "${{ secrets.API_TEST_KEY }}"}
        job_str = str(jobs[job_id])
        assert "VERCEL_TOKEN" not in job_str
        assert "FIREBASE_SERVICE_ACCOUNT" not in job_str

    # Deploy jobs require all parallel test job IDs
    assert jobs["deploy_vercel"]["needs"] == ["test-apps-web", "test-services-api"]
    assert jobs["deploy_firebase"]["needs"] == ["test-apps-web", "test-services-api"]

    # Polyglot root repo (non-monorepo) splits into test-node and test-python without path triggers
    poly_root_ctx = ProjectContext(
        repo_name="poly-root",
        repo_root="/poly",
        is_monorepo=False,
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
                test_cmd="npm test",
            ),
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
            ),
        ],
        services=[
            ServiceRequirement(
                name="postgres",
                image="postgres:16-alpine",
                ports=[5432],
                source_file="python dependencies",
                package_path=None,
            )
        ],
    )
    poly_doc = YAML(typ="safe").load(GitHubActionsSynthesizer().synthesize(poly_root_ctx)[".github/workflows/ci.yml"])
    assert set(poly_doc["jobs"].keys()) == {"test-node", "test-python"}
    assert "paths" not in poly_doc["on"]["push"]
    assert "postgres" in poly_doc["jobs"]["test-python"]["services"]
    assert "services" not in poly_doc["jobs"]["test-node"]


def test_matrix_synthesis_versions_and_os_across_jobs():
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator

    # 1. Single-root Python project with multi-version + multi-OS matrix
    single_ctx = ProjectContext(
        repo_name="matrix-py",
        repo_root="/matrix-py",
        matrix_os=["ubuntu-latest", "macos-latest"],
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="pip",
                install_cmd="pip install -e .",
                test_cmd="pytest",
                matrix_versions=["3.10", "3.11", "3.12"],
            )
        ],
    )
    single_yaml = GitHubActionsSynthesizer().synthesize(single_ctx)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", single_yaml)
    assert is_valid, f"Validation failed: {errors}"
    assert "'3.10'" in single_yaml or '"3.10"' in single_yaml

    single_doc = YAML(typ="safe").load(single_yaml)
    test_job = single_doc["jobs"]["test"]
    assert test_job["runs-on"] == "${{ matrix.os }}"
    assert test_job["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "os": ["ubuntu-latest", "macos-latest"],
            "python-version": ["3.10", "3.11", "3.12"],
        },
    }
    assert test_job["strategy"]["matrix"]["python-version"][0] == "3.10"
    setup_py = next(s for s in test_job["steps"] if "actions/setup-python" in s.get("uses", ""))
    assert setup_py["with"]["python-version"] == "${{ matrix.python-version }}"
    assert "${{ matrix.python-version }}" in setup_py["name"]

    # 2. Multi-job polyglot monorepo with Node, Python (uv), Go, Rust matrices and OS matrix
    mono_ctx = ProjectContext(
        repo_name="matrix-mono",
        repo_root="/matrix-mono",
        is_monorepo=True,
        matrix_os=["ubuntu-latest", "macos-latest"],
        monorepo_packages=[
            MonorepoPackage(
                name="web",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                runtime_version="22.x",
                install_cmd="pnpm i",
                test_cmd="pnpm test",
                matrix_versions=["18.x", "20.x", "22.x"],
            ),
            MonorepoPackage(
                name="api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                install_cmd="uv sync",
                test_cmd="uv run pytest",
                matrix_versions=["3.10", "3.12"],
            ),
            MonorepoPackage(
                name="worker",
                path="services/worker",
                language="go",
                package_manager="gomod",
                runtime_version="1.22",
                install_cmd="go mod download",
                test_cmd="go test ./...",
                matrix_versions=["1.20", "1.22"],
            ),
            MonorepoPackage(
                name="core",
                path="crates/core",
                language="rust",
                package_manager="cargo",
                runtime_version="stable",
                install_cmd=None,
                test_cmd="cargo test",
                matrix_versions=["stable", "beta"],
            ),
        ],
    )
    mono_yaml = GitHubActionsSynthesizer().synthesize(mono_ctx)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", mono_yaml)
    assert is_valid, f"Validation failed: {errors}"
    assert "'1.20'" in mono_yaml or '"1.20"' in mono_yaml
    assert "'3.10'" in mono_yaml or '"3.10"' in mono_yaml

    mono_doc = YAML(typ="safe").load(mono_yaml)
    jobs = mono_doc["jobs"]

    assert jobs["test-apps-web"]["runs-on"] == "${{ matrix.os }}"
    assert jobs["test-apps-web"]["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "os": ["ubuntu-latest", "macos-latest"],
            "node-version": ["18.x", "20.x", "22.x"],
        },
    }
    web_node = next(s for s in jobs["test-apps-web"]["steps"] if "actions/setup-node" in s.get("uses", ""))
    assert web_node["with"]["node-version"] == "${{ matrix.node-version }}"

    assert jobs["test-services-api"]["strategy"]["matrix"]["python-version"] == ["3.10", "3.12"]
    api_py = next(s for s in jobs["test-services-api"]["steps"] if "actions/setup-python" in s.get("uses", ""))
    assert api_py["with"]["python-version"] == "${{ matrix.python-version }}"

    assert jobs["test-services-worker"]["strategy"]["matrix"]["go-version"] == ["1.20", "1.22"]
    worker_go = next(s for s in jobs["test-services-worker"]["steps"] if "actions/setup-go" in s.get("uses", ""))
    assert worker_go["with"]["go-version"] == "${{ matrix.go-version }}"

    assert jobs["test-crates-core"]["strategy"]["matrix"]["toolchain"] == ["stable", "beta"]
    core_rs = next(s for s in jobs["test-crates-core"]["steps"] if "dtolnay/rust-toolchain" in s.get("uses", ""))
    assert core_rs["with"]["toolchain"] == "${{ matrix.toolchain }}"


def test_matrix_synthesis_cpp_cross_os_and_single_pin_non_matrix():
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator

    # 1. C++ OS matrix emits runner.os-conditional install steps
    cpp_matrix_ctx = ProjectContext(
        repo_name="cpp-matrix",
        repo_root="/cpp",
        matrix_os=["ubuntu-latest", "macos-latest", "windows-latest"],
        languages=[
            LanguageContext(
                language="cpp",
                runtime_version="c++20",
                version_source="CMakeLists.txt",
                package_manager="cmake",
                install_cmd="cmake -B build -S .",
                build_cmd="cmake --build build",
                test_cmd="ctest --test-dir build --output-on-failure",
                lint_cmd="clang-tidy -p build",
            )
        ],
    )
    cpp_yaml = GitHubActionsSynthesizer().synthesize(cpp_matrix_ctx)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", cpp_yaml)
    assert is_valid, f"Validation failed: {errors}"

    cpp_doc = YAML(typ="safe").load(cpp_yaml)
    cpp_job = cpp_doc["jobs"]["test"]
    assert cpp_job["runs-on"] == "${{ matrix.os }}"
    assert cpp_job["strategy"] == {
        "fail-fast": False,
        "matrix": {"os": ["ubuntu-latest", "macos-latest", "windows-latest"]},
    }

    steps = cpp_job["steps"]
    linux_step = next(s for s in steps if s.get("if") == "runner.os == 'Linux'")
    mac_step = next(s for s in steps if s.get("if") == "runner.os == 'macOS'")
    win_step = next(s for s in steps if s.get("if") == "runner.os == 'Windows'")
    assert "apt-get install -y cmake ninja-build build-essential clang-tidy" in linux_step["run"]
    assert "brew install cmake ninja" in mac_step["run"]
    assert "choco install cmake ninja" in win_step["run"]

    # 2. Single-pin project (empty or 1-element matrix lists) emits NO strategy block
    single_pin_ctx = ProjectContext(
        repo_name="single-pin",
        repo_root="/single",
        matrix_os=["ubuntu-latest"],
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
                matrix_versions=["3.12"],
            )
        ],
    )
    single_pin_yaml = GitHubActionsSynthesizer().synthesize(single_pin_ctx)[".github/workflows/ci.yml"]
    single_pin_doc = YAML(typ="safe").load(single_pin_yaml)
    assert "strategy" not in single_pin_doc["jobs"]["test"]
    assert single_pin_doc["jobs"]["test"]["runs-on"] == "ubuntu-latest"
    assert "matrix." not in single_pin_yaml

    # 3. Selective matrix per monorepo job: one job matrixed, sibling job single-pin without strategy
    mixed_mono = ProjectContext(
        repo_name="selective-matrix",
        repo_root="/sel",
        is_monorepo=True,
        monorepo_packages=[
            MonorepoPackage(
                name="web",
                path="apps/web",
                language="node",
                package_manager="npm",
                runtime_version="20.x",
                install_cmd="npm ci",
                test_cmd="npm test",
                matrix_versions=["18.x", "20.x"],
            ),
            MonorepoPackage(
                name="api",
                path="services/api",
                language="python",
                package_manager="pip",
                runtime_version="3.12",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
                matrix_versions=[],
            ),
        ],
    )
    mixed_doc = YAML(typ="safe").load(GitHubActionsSynthesizer().synthesize(mixed_mono)[".github/workflows/ci.yml"])
    assert "strategy" in mixed_doc["jobs"]["test-apps-web"]
    assert mixed_doc["jobs"]["test-apps-web"]["runs-on"] == "ubuntu-latest"
    assert "strategy" not in mixed_doc["jobs"]["test-services-api"]


def test_dependabot_monorepo_polyglot_deduped():
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator

    context = ProjectContext(
        repo_name="poly-dependabot",
        repo_root="/mono",
        is_monorepo=True,
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source="package.json",
                package_manager="pnpm",
                install_cmd="pnpm i",
                is_workspace_root=True,
            ),
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="uv",
                install_cmd="uv sync",
                is_workspace_root=None,
            ),
            LanguageContext(
                language="go",
                runtime_version="1.22",
                version_source="go.work",
                package_manager="gomod",
                install_cmd="go mod download",
                is_workspace_root=True,
            ),
            LanguageContext(
                language="rust",
                runtime_version="stable",
                version_source="Cargo.toml",
                package_manager="cargo",
                install_cmd="cargo fetch",
                is_workspace_root=True,
            ),
        ],
        monorepo_packages=[
            MonorepoPackage(name="web", path="./apps/web/", language="node", package_manager="pnpm"),
            MonorepoPackage(name="web-dup", path="apps/web", language="node", package_manager="pnpm"),
            MonorepoPackage(name="api", path="services/api", language="python", package_manager="uv"),
            MonorepoPackage(name="core", path="crates/core", language="rust", package_manager="cargo"),
            MonorepoPackage(name="auth", path="services/auth", language="go", package_manager="gomod"),
            MonorepoPackage(name="engine", path="services/engine", language="cpp", package_manager="cmake"),
        ],
        containers=[
            ContainerContext(dockerfile_path="Dockerfile"),
            ContainerContext(dockerfile_path="apps/web/Dockerfile"),
            ContainerContext(dockerfile_path="apps/web/Dockerfile.prod"),
            ContainerContext(dockerfile_path="./services/api/Dockerfile"),
        ],
    )

    dep_yaml = MaintenanceSynthesizer().synthesize(context)[".github/dependabot.yml"]
    is_valid, errors = PreflightValidator().validate(".github/dependabot.yml", dep_yaml)
    assert is_valid, f"Validation failed: {errors}"

    doc = YAML(typ="safe").load(dep_yaml)
    assert doc["version"] == 2
    pairs = [(u["package-ecosystem"], u["directory"]) for u in doc["updates"]]
    assert len(pairs) == len(set(pairs)), f"Duplicate Dependabot entries found: {pairs}"

    expected_pairs = {
        ("github-actions", "/"),
        ("npm", "/apps/web"),
        ("pip", "/services/api"),
        ("cargo", "/crates/core"),
        ("gomod", "/services/auth"),
        ("docker", "/"),
        ("docker", "/apps/web"),
        ("docker", "/services/api"),
    }
    assert set(pairs) == expected_pairs

    # Hybrid monorepo: active root Python + sub-package Node emits ("pip", "/") and ("npm", "/apps/web")
    hybrid_ctx = ProjectContext(
        repo_name="hybrid-dep",
        repo_root="/hybrid",
        is_monorepo=True,
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="pip",
                install_cmd="pip install -e .",
                working_dir=".",
                is_workspace_root=False,
            ),
            # Duplicate root Python entry should be deduplicated
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="pip",
                install_cmd="pip install -e .",
                working_dir=".",
                is_workspace_root=False,
            ),
        ],
        monorepo_packages=[
            MonorepoPackage(name="web", path="apps/web", language="node", package_manager="npm"),
        ],
    )
    hybrid_yaml = MaintenanceSynthesizer().synthesize(hybrid_ctx)[".github/dependabot.yml"]
    hybrid_doc = YAML(typ="safe").load(hybrid_yaml)
    hybrid_pairs = [(u["package-ecosystem"], u["directory"]) for u in hybrid_doc["updates"]]
    assert len(hybrid_pairs) == len(set(hybrid_pairs))
    assert set(hybrid_pairs) == {("github-actions", "/"), ("pip", "/"), ("npm", "/apps/web")}


def test_ci_template_decoupling_and_local_override(tmp_path: Path):
    import re
    import pytest
    from jinja2 import PackageLoader
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator
    from heurix.synthesizers.github_actions import (
        ACTION_VERSIONS,
        MATRIX_VERSION_KEYS,
        GitHubActionsSynthesizer,
        _collect_build_units,
        _normalize_working_dir,
        _scope_services_for_units,
        sanitize_job_id,
    )
    from heurix.synthesizers.templating import create_template_environment

    # Preserved module-level exports
    assert "actions/checkout" in ACTION_VERSIONS
    assert MATRIX_VERSION_KEYS["python"] == "python-version"
    assert _normalize_working_dir("./apps/web/") == "apps/web"
    assert callable(_collect_build_units)
    assert callable(_scope_services_for_units)
    assert callable(sanitize_job_id)

    # Bundled workflows/ci.yml.j2 exists in PackageLoader
    pkg_loader = PackageLoader("heurix", "templates")
    src, _, _ = pkg_loader.get_source(create_template_environment(), "workflows/ci.yml.j2")
    assert "macros/actions.j2" in src

    checkout_sha = "b4ffde65f46336ab88eb53be808477a3936bae11"
    context = ProjectContext(
        repo_name="tpl-ci-app",
        repo_root=str(tmp_path),
        is_monorepo=True,
        monorepo_packages=[
            MonorepoPackage(
                name="api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
                matrix_versions=["3.10", "3.12"],
            ),
            MonorepoPackage(
                name="worker",
                path="services/worker",
                language="go",
                package_manager="gomod",
                runtime_version="1.22",
                install_cmd="go mod download",
                test_cmd="go test ./...",
                matrix_versions=["1.20", "1.22"],
            ),
        ],
        policy_config={
            "ci": {
                "action_shas": {"actions/checkout": checkout_sha},
            }
        },
    )

    ci_yaml = GitHubActionsSynthesizer().synthesize(context)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", ci_yaml)
    assert is_valid, f"Validation failed: {errors}"

    assert ci_yaml.startswith("# Synthesized deterministically by Heurix (hx)\n")
    assert "# Non-destructive updates: preserve blocks marked with # @heurix:preserve" in ci_yaml
    assert re.search(rf"uses: actions/checkout@{checkout_sha}\s+# v4", ci_yaml)
    assert "'3.10'" in ci_yaml
    assert "'1.20'" in ci_yaml

    doc = YAML(typ="safe").load(ci_yaml)
    assert doc["jobs"]["test-services-api"]["strategy"]["matrix"]["python-version"] == ["3.10", "3.12"]
    assert doc["jobs"]["test-services-worker"]["strategy"]["matrix"]["go-version"] == ["1.20", "1.22"]

    # Repo-local .heurix/templates/workflows/ci.yml.j2 overrides bundled template via ChoiceLoader
    override_dir = tmp_path / ".heurix" / "templates" / "workflows"
    override_dir.mkdir(parents=True)
    (override_dir / "ci.yml.j2").write_text(
        "# Custom local workflow template\n"
        '{% from "macros/actions.j2" import render_step %}\n'
        "name: Custom CI\n"
        "on:\n"
        "  push:\n"
        "    branches:\n"
        "{% for branch in on.get('push', {}).get('branches', []) %}\n"
        "      - {{ branch | yaml_scalar }}\n"
        "{% endfor %}\n"
        "jobs:\n"
        "{% for job_id, job in jobs.items() %}\n"
        "  {{ job_id }}:\n"
        "    runs-on: {{ job.get('runs-on', 'ubuntu-latest') | yaml_scalar }}\n"
        "    steps:\n"
        "{% for step in job.get('steps', []) %}\n"
        "{{ render_step(step, base_indent=6) }}"
        "{% endfor %}\n"
        "{% endfor %}\n",
        encoding="utf-8",
    )

    custom_yaml = GitHubActionsSynthesizer().synthesize(context)[".github/workflows/ci.yml"]
    is_custom_valid, custom_errors = PreflightValidator().validate(".github/workflows/ci.yml", custom_yaml)
    assert is_custom_valid, f"Custom override validation failed: {custom_errors}"
    assert "# Custom local workflow template" in custom_yaml
    assert "name: Custom CI" in custom_yaml
    assert re.search(rf"uses: actions/checkout@{checkout_sha}\s+# v4", custom_yaml)

    # Custom [engine].templates_dir also takes precedence when contained inside repo_root
    alt_dir = tmp_path / "alt_templates" / "workflows"
    alt_dir.mkdir(parents=True)
    (alt_dir / "ci.yml.j2").write_text(
        "# Alt templates_dir override\n"
        "name: Alt CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Checkout\n"
        "        uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    alt_ctx = context.model_copy(
        update={
            "policy_config": {
                "engine": {"templates_dir": "alt_templates"},
            }
        }
    )
    alt_yaml = GitHubActionsSynthesizer().synthesize(alt_ctx)[".github/workflows/ci.yml"]
    assert "# Alt templates_dir override" in alt_yaml
    assert "name: Alt CI" in alt_yaml

    # SEC-01: Out-of-repo templates_dir is rejected
    bad_ctx = context.model_copy(
        update={
            "policy_config": {
                "engine": {"templates_dir": "../outside_templates"},
            }
        }
    )
    with pytest.raises(ValueError, match="Path traversal security violation"):
        GitHubActionsSynthesizer().synthesize(bad_ctx)


def test_policy_runners_linters_and_step_injections(tmp_path: Path):
    import re
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator

    codecov_sha = "1234567890abcdef1234567890abcdef12345678"
    context = ProjectContext(
        repo_name="policy-ci",
        repo_root="/demo",
        is_monorepo=True,
        matrix_os=["ubuntu-latest", "macos-latest"],
        monorepo_packages=[
            MonorepoPackage(
                name="web",
                path="apps/web",
                language="node",
                package_manager="npm",
                runtime_version="20.x",
                install_cmd="npm ci",
                lint_cmd="npm run lint",
                build_cmd="npm run build",
                test_cmd="npm test",
                matrix_versions=["18.x", "20.x"],
            ),
            MonorepoPackage(
                name="api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                install_cmd="uv sync --frozen",
                lint_cmd="uv run ruff check .",
                test_cmd="uv run pytest",
            ),
            MonorepoPackage(
                name="gateway",
                path="services/go",
                language="go",
                package_manager="gomod",
                runtime_version="1.22",
                install_cmd="go mod download",
                lint_cmd="golangci-lint run",
                build_cmd="go build ./...",
                test_cmd="go test ./...",
            ),
            MonorepoPackage(
                name="engine",
                path="services/cpp",
                language="cpp",
                package_manager="cmake",
                runtime_version="c++20",
                install_cmd="cmake -B build -S .",
                build_cmd="cmake --build build",
                lint_cmd="clang-tidy -p build",
                test_cmd="ctest --test-dir build",
            ),
        ],
        services=[
            ServiceRequirement(name="postgres", image="postgres:16-alpine", ports=[5432]),
            ServiceRequirement(name="redis", image="redis:7-alpine", ports=[6379]),
            ServiceRequirement(name="mongodb", image="mongo:7", ports=[27017]),
        ],
        env_vars={"BASE_ENV": "keep", "PROMOTE_ME": "old-plain", "RAW_TOKEN": "bad"},
        test_secrets=["EXISTING_TEST_SECRET", "DOCKER_PASSWORD"],
        deployment_secrets=["FIREBASE_SERVICE_ACCOUNT"],
        deployment_targets=[
            DeploymentTarget(
                platform="vercel",
                config_file="vercel.json",
                project_id="policy-ci",
                required_secrets=["VERCEL_TOKEN"],
            ),
            DeploymentTarget(
                platform="firebase",
                config_file="firebase.json",
                project_id="policy-ci-fb",
                required_secrets=["FIREBASE_SERVICE_ACCOUNT"],
            ),
        ],
        policy_config={
            "ci": {
                "pin_actions": True,
                "action_shas": {"codecov/codecov-action": codecov_sha},
                "runners": {
                    "test-apps-web": "ubuntu-22.04",
                    "test-services-cpp": "macos-latest",
                    "deploy_vercel": "ubuntu-22.04",
                    "deploy_firebase": "ubuntu-24.04",
                },
                "steps": {
                    "pre_test": [
                        {"name": "Global pre-test", "run": "echo global-pre"},
                    ],
                    "post_test": [
                        {
                            "name": "Upload coverage",
                            "uses": "codecov/codecov-action@v4",
                            "with": {"fail_ci_if_error": False},
                        }
                    ],
                },
            },
            "jobs": {
                "test-apps-web": {
                    "runner": "ubuntu-24.04-arm",
                    "pre_steps": [{"name": "Web pre-step", "run": "echo web-pre"}],
                    "post_steps": [{"name": "Web post-step", "run": "echo web-post"}],
                },
                "deploy_vercel": {
                    "runner": "self-hosted",
                    "pre_steps": [{"name": "Prepare Vercel", "run": "echo pre-vercel"}],
                    "post_steps": [{"name": "Notify Vercel", "run": "echo post-vercel"}],
                },
            },
            "services": {"exclude": ["postgresql", "Redis"]},
            "linters": {"enabled": True, "python": False, "go": False, "cpp": False},
            "env": {
                "APP_ENV": "staging",
                "PORT": 8080,
                "API_SECRET": "leaked-secret",
                "DATABASE_URL": "postgres://leaked",
                "CUSTOM_SERVICE_ACCOUNT": "{}",
            },
            "secrets": {
                "deploy": ["PROMOTE_ME", "CUSTOM_DEPLOY_SECRET"],
                "test": ["POLICY_TEST_SECRET", "VERCEL_TOKEN", "AWS_SECRET_ACCESS_KEY", "PROMOTE_ME"],
            },
        },
    )

    ci_yaml = GitHubActionsSynthesizer().synthesize(context)[".github/workflows/ci.yml"]
    is_valid, errors = PreflightValidator().validate(".github/workflows/ci.yml", ci_yaml)
    assert is_valid, f"Validation failed: {errors}"

    doc = YAML(typ="safe").load(ci_yaml)
    jobs = doc["jobs"]

    # 1. Per-job runner precedence & selective matrix.os omission
    web_job = jobs["test-apps-web"]
    assert web_job["runs-on"] == "ubuntu-24.04-arm"
    assert web_job["strategy"]["matrix"] == {"node-version": ["18.x", "20.x"]}
    assert "os" not in web_job["strategy"]["matrix"]

    cpp_job = jobs["test-services-cpp"]
    assert cpp_job["runs-on"] == "macos-latest"
    assert "strategy" not in cpp_job
    cpp_runs = [s.get("run", "") for s in cpp_job["steps"]]
    assert "brew install cmake ninja" in cpp_runs
    assert not any(s.get("if") == "runner.os == 'Linux'" for s in cpp_job["steps"])

    api_job = jobs["test-services-api"]
    assert api_job["runs-on"] == "${{ matrix.os }}"
    assert api_job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "macos-latest"]

    assert jobs["deploy_vercel"]["runs-on"] == "self-hosted"
    assert jobs["deploy_firebase"]["runs-on"] == "ubuntu-24.04"

    # 2. [services].exclude applied even on direct ProjectContext synthesis
    for test_id in ("test-apps-web", "test-services-api", "test-services-go", "test-services-cpp"):
        svc_keys = set(jobs[test_id].get("services", {}).keys())
        assert svc_keys == {"mongodb"}, f"Unexpected services on {test_id}: {svc_keys}"

    # 3. [linters] suppression across Python, Go, C++ while keeping Node enabled
    assert any(s.get("name") == "Lint code (node)" for s in web_job["steps"])
    assert not any(s.get("name") == "Lint code (python)" for s in api_job["steps"])
    assert not any("golangci-lint-action" in str(s.get("uses", "")) for s in jobs["test-services-go"]["steps"])
    assert not any("clang-tidy" in str(s.get("run", "")) for s in cpp_job["steps"])
    assert not any(s.get("name") == "Lint code (cpp)" for s in cpp_job["steps"])

    # Also test C++ on Linux runner with cpp linter disabled -> omits clang-tidy from apt-get
    cpp_linux_ctx = ProjectContext(
        repo_name="cpp-linux",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="cpp",
                runtime_version="c++20",
                version_source="CMakeLists.txt",
                package_manager="cmake",
                install_cmd="cmake -B build -S .",
                build_cmd="cmake --build build",
                test_cmd="ctest --test-dir build",
                lint_cmd="clang-tidy -p build",
            )
        ],
        policy_config={"linters": {"cpp": False}},
    )
    cpp_linux_doc = YAML(typ="safe").load(
        GitHubActionsSynthesizer().synthesize(cpp_linux_ctx)[".github/workflows/ci.yml"]
    )
    cpp_linux_runs = [s.get("run", "") for s in cpp_linux_doc["jobs"]["test"]["steps"]]
    assert any("sudo apt-get update && sudo apt-get install -y cmake ninja-build build-essential" in r for r in cpp_linux_runs)
    assert not any("clang-tidy" in r for r in cpp_linux_runs)

    # Global [linters].enabled = False suppresses Node linter too
    global_off_ctx = context.model_copy(
        update={"policy_config": {"linters": {"enabled": False}}}
    )
    global_off_doc = YAML(typ="safe").load(
        GitHubActionsSynthesizer().synthesize(global_off_ctx)[".github/workflows/ci.yml"]
    )
    assert not any(s.get("name") == "Lint code (node)" for s in global_off_doc["jobs"]["test-apps-web"]["steps"])

    # 4. Step ordering and external action SHA pinning + EOL comment
    web_names = [s.get("name") for s in web_job["steps"]]
    assert web_names == [
        "Checkout repository",
        "Set up Node.js ${{ matrix.node-version }}",
        "Install dependencies",
        "Global pre-test",
        "Web pre-step",
        "Lint code (node)",
        "Build (node)",
        "Run tests (node)",
        "Web post-step",
        "Upload coverage",
    ]
    assert re.search(rf"uses: codecov/codecov-action@{codecov_sha}\s+# v4", ci_yaml)
    cov_step = next(s for s in web_job["steps"] if s.get("name") == "Upload coverage")
    assert cov_step["uses"] == f"codecov/codecov-action@{codecov_sha}"
    assert cov_step["with"] == {"fail_ci_if_error": False}

    vercel_names = [s.get("name") for s in jobs["deploy_vercel"]["steps"]]
    assert vercel_names == [
        "Checkout repository",
        "Prepare Vercel",
        "Deploy to Vercel (Production)",
        "Notify Vercel",
    ]
    assert "Global pre-test" not in vercel_names
    assert "Upload coverage" not in vercel_names

    # 5. SEC-02 & SEC-03 enforcement on direct ProjectContext synthesis
    test_step = next(s for s in web_job["steps"] if s.get("name") == "Run tests (node)")
    assert test_step["env"] == {
        "BASE_ENV": "keep",
        "APP_ENV": "staging",
        "PORT": "8080",
        "EXISTING_TEST_SECRET": "${{ secrets.EXISTING_TEST_SECRET }}",
        "POLICY_TEST_SECRET": "${{ secrets.POLICY_TEST_SECRET }}",
    }
    for forbidden in (
        "RAW_TOKEN",
        "API_SECRET",
        "DATABASE_URL",
        "CUSTOM_SERVICE_ACCOUNT",
        "PROMOTE_ME",
        "CUSTOM_DEPLOY_SECRET",
        "VERCEL_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "DOCKER_PASSWORD",
        "FIREBASE_SERVICE_ACCOUNT",
    ):
        assert forbidden not in str(web_job)

    # 6. Direct [engine].runner & pin_actions=False on single-root ProjectContext
    direct_single_ctx = ProjectContext(
        repo_name="single-direct",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
            )
        ],
        policy_config={
            "engine": {"runner": "ubuntu-24.04"},
            "ci": {
                "pin_actions": False,
                "action_shas": {"codecov/codecov-action": codecov_sha},
                "steps": {
                    "post_test": [{"name": "Upload cov", "uses": "codecov/codecov-action@v4"}],
                },
            },
        },
    )
    direct_single_yaml = GitHubActionsSynthesizer().synthesize(direct_single_ctx)[".github/workflows/ci.yml"]
    direct_single_doc = YAML(typ="safe").load(direct_single_yaml)
    assert direct_single_doc["jobs"]["test"]["runs-on"] == "ubuntu-24.04"
    assert any(
        s.get("uses") == "codecov/codecov-action@v4"
        for s in direct_single_doc["jobs"]["test"]["steps"]
    )

    # 7. End-to-end analyze_repository() + GitHubActionsSynthesizer parity
    from heurix.detectors import analyze_repository

    repo = tmp_path / "e2e_policy_repo"
    repo.mkdir(parents=True)
    (repo / "uv.lock").write_text("", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "api"\nrequires-python = ">=3.12"\ndependencies = ["fastapi", "redis", "pytest", "ruff"]\n',
        encoding="utf-8",
    )
    (repo / ".heurix.toml").write_text(
        """
[engine]
runner = "ubuntu-24.04"

[services]
exclude = ["redis"]

[linters]
python = false

[ci.runners]
test = "ubuntu-22.04"

[[ci.steps.pre_test]]
name = "Pre-flight check"
run = "echo ready"
""",
        encoding="utf-8",
    )
    analyzed = analyze_repository(repo)
    e2e_yaml = GitHubActionsSynthesizer().synthesize(analyzed)[".github/workflows/ci.yml"]
    e2e_valid, e2e_errors = PreflightValidator().validate(".github/workflows/ci.yml", e2e_yaml)
    assert e2e_valid, f"E2E validation failed: {e2e_errors}"
    e2e_doc = YAML(typ="safe").load(e2e_yaml)
    assert e2e_doc["jobs"]["test"]["runs-on"] == "ubuntu-22.04"
    assert "services" not in e2e_doc["jobs"]["test"]
    e2e_names = [s.get("name") for s in e2e_doc["jobs"]["test"]["steps"]]
    assert "Pre-flight check" in e2e_names
    assert "Lint code (python)" not in e2e_names


def test_dependabot_template_decoupling(tmp_path: Path):
    import pytest
    from jinja2 import PackageLoader
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator
    from heurix.synthesizers.maintenance import ECOSYSTEM_MAP, MaintenanceSynthesizer, _normalize_dir
    from heurix.synthesizers.templating import create_template_environment

    assert ECOSYSTEM_MAP["python"] == "pip"
    assert _normalize_dir("./apps/web/") == "/apps/web"

    pkg_loader = PackageLoader("heurix", "templates")
    src, _, _ = pkg_loader.get_source(create_template_environment(), "dependabot/dependabot.yml.j2")
    assert "updates" in src

    context = ProjectContext(
        repo_name="dep-tpl-app",
        repo_root=str(tmp_path),
        is_monorepo=True,
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="pyproject.toml",
                package_manager="uv",
                install_cmd="uv sync",
                working_dir=".",
                is_workspace_root=False,
            )
        ],
        monorepo_packages=[
            MonorepoPackage(name="web", path="./apps/web/", language="node", package_manager="pnpm"),
            MonorepoPackage(name="web-dup", path="apps/web", language="node", package_manager="pnpm"),
        ],
        containers=[
            ContainerContext(dockerfile_path="Dockerfile"),
            ContainerContext(dockerfile_path="apps/web/Dockerfile"),
        ],
    )

    dep_yaml = MaintenanceSynthesizer().synthesize(context)[".github/dependabot.yml"]
    is_valid, errors = PreflightValidator().validate(".github/dependabot.yml", dep_yaml)
    assert is_valid, f"Validation failed: {errors}"
    assert dep_yaml.startswith("# Synthesized deterministically by Heurix (hx)\n")

    doc = YAML(typ="safe").load(dep_yaml)
    assert doc["version"] == 2
    assert [(u["package-ecosystem"], u["directory"], u["open-pull-requests-limit"]) for u in doc["updates"]] == [
        ("github-actions", "/", 10),
        ("pip", "/", 10),
        ("npm", "/apps/web", 5),
        ("docker", "/", 10),
        ("docker", "/apps/web", 10),
    ]

    # Local .heurix/templates/dependabot/dependabot.yml.j2 override takes precedence via ChoiceLoader
    override_dir = tmp_path / ".heurix" / "templates" / "dependabot"
    override_dir.mkdir(parents=True)
    (override_dir / "dependabot.yml.j2").write_text(
        "# Custom local Dependabot template\n"
        "version: 2\n"
        "updates:\n"
        "{% for update in updates %}\n"
        "  - package-ecosystem: {{ update['package-ecosystem'] | yaml_scalar }}\n"
        "    directory: {{ update['directory'] | yaml_scalar }}\n"
        "    schedule:\n"
        "      interval: daily\n"
        "    open-pull-requests-limit: {{ update['open-pull-requests-limit'] | yaml_scalar }}\n"
        "{% endfor %}\n",
        encoding="utf-8",
    )

    custom_yaml = MaintenanceSynthesizer().synthesize(context)[".github/dependabot.yml"]
    is_custom_valid, custom_errors = PreflightValidator().validate(".github/dependabot.yml", custom_yaml)
    assert is_custom_valid, f"Custom Dependabot validation failed: {custom_errors}"
    assert "# Custom local Dependabot template" in custom_yaml
    custom_doc = YAML(typ="safe").load(custom_yaml)
    assert all(u["schedule"]["interval"] == "daily" for u in custom_doc["updates"])

    # SEC-01: Out-of-repo templates_dir is rejected
    bad_ctx = context.model_copy(
        update={"policy_config": {"engine": {"templates_dir": "../outside_dep"}}}
    )
    with pytest.raises(ValueError, match="Path traversal security violation"):
        MaintenanceSynthesizer().synthesize(bad_ctx)


def test_e2e_parallel_job_synthesis_and_combined_mode():
    from ruamel.yaml import YAML
    from heurix.core.context import MonorepoPackage
    from heurix.core.validator import PreflightValidator

    yaml = YAML(typ="safe")
    syn = GitHubActionsSynthesizer()
    validator = PreflightValidator()

    # 1. Single-root Node (vitest + playwright) splits into parallel test + test-e2e
    base_ctx = ProjectContext(
        repo_name="e2e-web",
        repo_root="/demo",
        matrix_os=["ubuntu-latest", "macos-latest"],
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
        deployment_targets=[
            DeploymentTarget(
                platform="vercel",
                config_file="vercel.json",
                project_id="e2e-web",
                required_secrets=["VERCEL_TOKEN"],
            )
        ],
        env_vars={
            "APP_ENV": "ci",
            "DATABASE_URL": "postgres://blocked",
            "VERCEL_TOKEN": "leaked-env",
        },
        test_secrets=["E2E_API_KEY", "VERCEL_TOKEN"],
        deployment_secrets=["VERCEL_TOKEN", "FIREBASE_SERVICE_ACCOUNT"],
        policy_config={
            "ci": {
                "runners": {"test-e2e": "ubuntu-24.04"},
                "steps": {
                    "pre_test": [{"name": "Unit pre-step", "run": "echo unit-pre"}],
                },
            },
            "jobs": {
                "test-e2e": {
                    "pre_steps": [{"name": "E2E pre-step", "run": "echo e2e-pre"}],
                    "post_steps": [{"name": "E2E post-step", "run": "echo e2e-post"}],
                }
            },
        },
    )

    split_yaml = syn.synthesize(base_ctx)[".github/workflows/ci.yml"]
    ok, errs = validator.validate(".github/workflows/ci.yml", split_yaml)
    assert ok, f"Split E2E validation failed: {errs}"
    doc = yaml.load(split_yaml)
    jobs = doc["jobs"]

    assert "test" in jobs
    assert "test-e2e" in jobs
    assert jobs["deploy_vercel"]["needs"] == ["test", "test-e2e"]

    e2e_job = jobs["test-e2e"]
    assert e2e_job["runs-on"] == "ubuntu-24.04"
    assert "strategy" not in e2e_job
    setup_node = next(s for s in e2e_job["steps"] if "actions/setup-node" in s.get("uses", ""))
    assert setup_node["with"]["node-version"] == "20.x"

    e2e_step_names = [s.get("name") for s in e2e_job["steps"]]
    assert "Unit pre-step" not in e2e_step_names
    assert e2e_step_names == [
        "Checkout repository",
        "Set up Node.js 20.x",
        "Install dependencies",
        "E2E pre-step",
        "Install Playwright browsers",
        "Run E2E tests (playwright)",
        "E2E post-step",
    ]
    pw_step = next(s for s in e2e_job["steps"] if s.get("name") == "Install Playwright browsers")
    assert pw_step["run"] == "npx playwright install --with-deps"

    e2e_run_step = next(s for s in e2e_job["steps"] if s.get("name") == "Run E2E tests (playwright)")
    assert e2e_run_step["run"] == "npm run test:e2e"
    assert e2e_run_step["env"] == {
        "APP_ENV": "ci",
        "E2E_API_KEY": "${{ secrets.E2E_API_KEY }}",
    }
    for forbidden in ("DATABASE_URL", "VERCEL_TOKEN", "FIREBASE_SERVICE_ACCOUNT"):
        assert forbidden not in str(e2e_job)

    # Without runner override, test-e2e inherits matrix_os
    matrix_ctx = base_ctx.model_copy(update={"policy_config": {}, "split_e2e_jobs": True})
    matrix_doc = yaml.load(syn.synthesize(matrix_ctx)[".github/workflows/ci.yml"])
    assert matrix_doc["jobs"]["test-e2e"]["runs-on"] == "${{ matrix.os }}"
    assert matrix_doc["jobs"]["test-e2e"]["strategy"] == {
        "fail-fast": False,
        "matrix": {"os": ["ubuntu-latest", "macos-latest"]},
    }

    # 2. Combined mode (split_e2e_jobs=False) runs E2E inside test without test-e2e job
    combined_ctx = base_ctx.model_copy(update={"split_e2e_jobs": False})
    combined_yaml = syn.synthesize(combined_ctx)[".github/workflows/ci.yml"]
    ok_comb, errs_comb = validator.validate(".github/workflows/ci.yml", combined_yaml)
    assert ok_comb, f"Combined E2E validation failed: {errs_comb}"
    comb_doc = yaml.load(combined_yaml)
    assert "test-e2e" not in comb_doc["jobs"]
    assert comb_doc["jobs"]["deploy_vercel"]["needs"] == "test"

    comb_steps = comb_doc["jobs"]["test"]["steps"]
    comb_names = [s.get("name") for s in comb_steps]
    assert "Install Playwright browsers" in comb_names
    assert "Run E2E tests (playwright)" in comb_names
    assert comb_names.index("Run tests (node)") < comb_names.index("Install Playwright browsers")
    assert comb_names.index("Install Playwright browsers") < comb_names.index("Run E2E tests (playwright)")
    comb_e2e_step = next(s for s in comb_steps if s.get("name") == "Run E2E tests (playwright)")
    assert comb_e2e_step["run"] == "npm run test:e2e"
    assert comb_e2e_step["env"] == {
        "APP_ENV": "ci",
        "E2E_API_KEY": "${{ secrets.E2E_API_KEY }}",
    }

    # Same test_cmd and e2e_cmd in combined mode must not emit duplicate E2E run step
    same_cmd_ctx = ProjectContext(
        repo_name="same-cmd",
        repo_root="/demo",
        split_e2e_jobs=False,
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
                test_cmd="npx playwright test",
                unit_test_runner="vitest",
                e2e_test_runner="playwright",
                e2e_cmd="npx playwright test",
            )
        ],
    )
    same_doc = yaml.load(syn.synthesize(same_cmd_ctx)[".github/workflows/ci.yml"])
    assert not any(
        s.get("name") == "Run E2E tests (playwright)"
        for s in same_doc["jobs"]["test"]["steps"]
    )

    # 3. Multi-E2E polyglot monorepo + cross-unit coexistence + pm-specific Playwright install cmds
    mono_ctx = ProjectContext(
        repo_name="poly-e2e",
        repo_root="/mono",
        is_monorepo=True,
        monorepo_packages=[
            MonorepoPackage(
                name="apps/web",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                runtime_version="20.x",
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
                package_manager="yarn",
                runtime_version="20.x",
                install_cmd="yarn install --frozen-lockfile",
                test_cmd="yarn test",
                unit_test_runner="jest",
                e2e_test_runner="cypress",
                e2e_cmd="yarn cypress run",
            ),
            MonorepoPackage(
                name="services/api",
                path="services/api",
                language="python",
                package_manager="uv",
                runtime_version="3.12",
                install_cmd="uv sync --frozen",
                test_cmd="uv run pytest",
                unit_test_runner="pytest",
                e2e_test_runner="playwright",
                e2e_cmd="uv run pytest tests/e2e",
            ),
        ],
        deployment_targets=[
            DeploymentTarget(
                platform="vercel",
                config_file="vercel.json",
                project_id="poly-e2e",
                required_secrets=["VERCEL_TOKEN"],
            )
        ],
    )
    mono_yaml = syn.synthesize(mono_ctx)[".github/workflows/ci.yml"]
    ok_mono, errs_mono = validator.validate(".github/workflows/ci.yml", mono_yaml)
    assert ok_mono, f"Mono E2E validation failed: {errs_mono}"
    mono_doc = yaml.load(mono_yaml)
    assert set(mono_doc["jobs"].keys()) == {
        "test-apps-admin",
        "test-apps-web",
        "test-services-api",
        "test-e2e",
        "test-e2e-2",
        "test-e2e-3",
        "deploy_vercel",
    }
    assert mono_doc["jobs"]["deploy_vercel"]["needs"] == [
        "test-apps-admin",
        "test-apps-web",
        "test-services-api",
        "test-e2e",
        "test-e2e-2",
        "test-e2e-3",
    ]
    # apps/admin uses cypress -> no Playwright install step
    assert mono_doc["jobs"]["test-e2e"]["defaults"]["run"]["working-directory"] == "apps/admin"
    assert not any(
        "playwright install" in s.get("run", "")
        for s in mono_doc["jobs"]["test-e2e"]["steps"]
    )
    # apps/web uses pnpm -> pnpm exec playwright install --with-deps
    assert mono_doc["jobs"]["test-e2e-2"]["defaults"]["run"]["working-directory"] == "apps/web"
    assert any(
        s.get("run") == "pnpm exec playwright install --with-deps"
        for s in mono_doc["jobs"]["test-e2e-2"]["steps"]
    )
    # services/api uses uv -> uv run playwright install --with-deps
    assert mono_doc["jobs"]["test-e2e-3"]["defaults"]["run"]["working-directory"] == "services/api"
    assert any(
        s.get("run") == "uv run playwright install --with-deps"
        for s in mono_doc["jobs"]["test-e2e-3"]["steps"]
    )

    # Cross-unit unit+E2E coexistence (Python pytest unit + Node bun playwright E2E)
    cross_ctx = ProjectContext(
        repo_name="cross-e2e",
        repo_root="/mono",
        is_monorepo=True,
        monorepo_packages=[
            MonorepoPackage(
                name="services/api",
                path="services/api",
                language="python",
                package_manager="pip",
                runtime_version="3.12",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
                unit_test_runner="pytest",
            ),
            MonorepoPackage(
                name="apps/e2e",
                path="apps/e2e",
                language="node",
                package_manager="bun",
                runtime_version="20.x",
                install_cmd="bun install --frozen-lockfile",
                e2e_test_runner="playwright",
                e2e_cmd="bunx playwright test",
            ),
        ],
    )
    cross_doc = yaml.load(syn.synthesize(cross_ctx)[".github/workflows/ci.yml"])
    assert "test-e2e" in cross_doc["jobs"]
    assert any(
        s.get("run") == "bunx playwright install --with-deps"
        for s in cross_doc["jobs"]["test-e2e"]["steps"]
    )

    # 4. Baseline parity when no e2e_test_runner exists
    plain_ctx = ProjectContext(
        repo_name="plain-py",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
                unit_test_runner="pytest",
            )
        ],
    )
    plain_default = syn.synthesize(plain_ctx)[".github/workflows/ci.yml"]
    plain_false = syn.synthesize(plain_ctx.model_copy(update={"split_e2e_jobs": False}))[
        ".github/workflows/ci.yml"
    ]
    assert plain_default == plain_false
    assert "test-e2e" not in plain_default


def test_github_actions_permissions_block_and_action_versions_policy():
    syn = GitHubActionsSynthesizer()
    ctx = ProjectContext(
        repo_name="perms-test",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                test_cmd="pytest",
            )
        ],
    )

    from ruamel.yaml import YAML
    yaml_parser = YAML(typ="safe")

    # 1. Default permissions: contents: read
    default_out = syn.synthesize(ctx)[".github/workflows/ci.yml"]
    default_doc = yaml_parser.load(default_out)
    assert default_doc["permissions"] == {"contents": "read"}
    assert "actions/setup-python@v5" in default_out

    # 2. Custom permissions and action_versions overrides via policy
    custom_ctx = ctx.model_copy(
        update={
            "policy_config": {
                "ci": {
                    "permissions": {"contents": "read", "pull-requests": "write"},
                    "action_versions": {
                        "actions/setup-python": "v7.1.0",
                        "actions/checkout": "v4.2.0",
                    },
                }
            }
        }
    )
    custom_out = syn.synthesize(custom_ctx)[".github/workflows/ci.yml"]
    custom_doc = yaml_parser.load(custom_out)
    assert custom_doc["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert "actions/setup-python@v7.1.0" in custom_out
    assert "actions/checkout@v4.2.0" in custom_out


def test_kubernetes_hardened_security_context_and_secret_wiring():
    from ruamel.yaml import YAML
    yaml_parser = YAML(typ="safe")
    k8s_syn = KubernetesSynthesizer()
    ctx = ProjectContext(
        repo_name="secure-app",
        repo_root="/demo",
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source="default",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
                framework="FastAPI",
            )
        ],
        containers=[
            ContainerContext(
                dockerfile_path="Dockerfile",
                exposed_ports=[8000],
            )
        ],
        required_secrets=["DATABASE_PASSWORD", "API_KEY"],
        env_vars={"APP_ENV": "production", "PORT": "8000"},
    )

    manifests = k8s_syn.synthesize(ctx)
    assert "k8s/deployment.yaml" in manifests
    assert "k8s/secret.yaml" in manifests
    assert "k8s/configmap.yaml" in manifests

    dep_doc = yaml_parser.load(manifests["k8s/deployment.yaml"])
    pod_sec = dep_doc["spec"]["template"]["spec"]["securityContext"]
    assert pod_sec["runAsNonRoot"] is True
    assert pod_sec["seccompProfile"]["type"] == "RuntimeDefault"

    container = dep_doc["spec"]["template"]["spec"]["containers"][0]
    c_sec = container["securityContext"]
    assert c_sec["allowPrivilegeEscalation"] is False
    assert c_sec["readOnlyRootFilesystem"] is True
    assert c_sec["capabilities"]["drop"] == ["ALL"]

    # envFrom wiring
    env_from = container["envFrom"]
    assert any("configMapRef" in ef for ef in env_from)
    assert any("secretRef" in ef for ef in env_from)

    # Secret manifest verification
    sec_doc = yaml_parser.load(manifests["k8s/secret.yaml"])
    assert sec_doc["kind"] == "Secret"
    assert "DATABASE_PASSWORD" in sec_doc["stringData"]
    assert "API_KEY" in sec_doc["stringData"]

