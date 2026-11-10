"""
Tests for YAML Synthesizers.
"""

from __future__ import annotations

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


