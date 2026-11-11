"""
Tests for typed HeurixPolicy schema, resilient field pruning, and IR policy application.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict

import pytest


def test_policy_schema_and_k8s_alias_validation():
    from heurix.core.policy import (
        DEPLOYMENT_SECRET_PREFIXES,
        SENSITIVE_KEYWORDS,
        CiPolicy,
        HeurixPolicy,
        StepPolicy,
        is_deployment_secret_key,
        is_sensitive_env_key,
        parse_heurix_policy,
    )

    # 1. Verify canonical SEC-02 / SEC-03 tokens and predicates without reverse detector imports
    assert len(SENSITIVE_KEYWORDS) == 14
    for token in (
        "SECRET",
        "PASSWORD",
        "TOKEN",
        "KEY",
        "AUTH",
        "PRIVATE",
        "CREDENTIAL",
        "CERT",
        "URL",
        "URI",
        "DSN",
        "CONN",
        "WEBHOOK",
        "SESSION",
    ):
        assert token in SENSITIVE_KEYWORDS

    assert DEPLOYMENT_SECRET_PREFIXES == ("VERCEL_", "FIREBASE_", "AWS_", "DOCKER_")
    assert is_sensitive_env_key("DATABASE_URL") is True
    assert is_sensitive_env_key("firebase_service_account") is True
    assert is_sensitive_env_key("LOG_LEVEL") is False
    assert is_deployment_secret_key("VERCEL_TOKEN") is True
    assert is_deployment_secret_key("aws_secret_access_key") is True
    assert is_deployment_secret_key("TEST_API_KEY") is False

    # Verify core/policy.py has zero reverse imports from heurix.detectors
    import heurix.core.policy as policy_mod

    source = Path(policy_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("heurix.detectors") for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("heurix.detectors")

    # 2. Full schema parsing with [k8s] -> [kubernetes] merge (kubernetes wins on overlap)
    raw_cfg: Dict[str, Any] = {
        "engine": {
            "runner": "ubuntu-24.04",
            "non_destructive": False,
            "templates_dir": ".heurix/custom-templates",
        },
        "ci": {
            "include_dependabot": False,
            "default_branch": "develop",
            "pin_actions": True,
            "action_shas": {"actions/checkout": "b4ffde65f46336ab88eb53be808477a3936bae11"},
            "runners": {"test-apps-web": "ubuntu-24.04-arm", "deploy_vercel": "ubuntu-22.04"},
            "steps": {
                "pre_test": [
                    {
                        "id": "migrate",
                        "name": "Run migrations",
                        "if": "github.event_name == 'push'",
                        "run": "uv run alembic upgrade head",
                        "working-directory": "services/api",
                        "continue-on-error": False,
                        "timeout-minutes": 10,
                        "env": {"PORT": 8000, "CI": True, "RATIO": 0.5},
                    }
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
                "runner": "self-hosted",
                "pre_steps": [{"name": "Prep web", "run": "echo prep"}],
                "post_steps": [{"name": "Archive web", "run": "echo archive"}],
            }
        },
        "matrix": {"os": ["ubuntu-latest", "macos-latest"], "python": ["3.11", "3.12"]},
        "overrides": {"python": "3.12"},
        "services": {"exclude": ["redis", "postgresql"]},
        "env": {"APP_ENV": "staging", "PORT": 8080, "FEATURE_FLAG": True, "THRESHOLD": 1.25},
        "secrets": {"test": ["API_KEY"], "deploy": ["VERCEL_TOKEN"]},
        "linters": {"enabled": True, "python": False, "go": True},
        "k8s": {
            "replicas": 3,
            "namespace": "staging-ns",
            "service_type": "NodePort",
            "resources": {
                "requests": {"cpu": "150m", "memory": "256Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
            "liveness_probe": {"enabled": True, "type": "httpGet", "path": "/livez", "port": 8000},
        },
        "kubernetes": {
            "replicas": 5,
            "image": "ghcr.io/acme/api:v2",
            "port": 9000,
            "resources": {
                "requests": {"cpu": "300m"},
            },
            "readiness_probe": {
                "enabled": True,
                "type": "exec",
                "command": ["python", "-c", "import sys; sys.exit(0)"],
                "initial_delay_seconds": 3,
                "period_seconds": 5,
                "timeout_seconds": 2,
                "failure_threshold": 4,
            },
            "hpa": {
                "enabled": True,
                "min_replicas": 2,
                "max_replicas": 8,
                "target_cpu_utilization": 70,
            },
        },
    }

    policy, warnings = parse_heurix_policy(raw_cfg)
    assert warnings == []
    assert policy.engine.runner == "ubuntu-24.04"
    assert policy.engine.non_destructive is False
    assert policy.engine.templates_dir == ".heurix/custom-templates"

    # Research Pitfall 5: include_k8s defaults to None when omitted
    assert CiPolicy().include_k8s is None
    assert policy.ci.include_k8s is None
    assert policy.ci.include_dependabot is False
    assert policy.ci.default_branch == "develop"
    assert policy.ci.runners["test-apps-web"] == "ubuntu-24.04-arm"

    pre_step = policy.ci.steps.pre_test[0]
    assert pre_step.if_ == "github.event_name == 'push'"
    assert pre_step.working_directory == "services/api"
    assert pre_step.continue_on_error is False
    assert pre_step.timeout_minutes == 10
    assert pre_step.env == {"PORT": "8000", "CI": "true", "RATIO": "0.5"}
    step_dict = pre_step.to_step_dict()
    assert step_dict["if"] == "github.event_name == 'push'"
    assert step_dict["working-directory"] == "services/api"
    assert step_dict["continue-on-error"] is False
    assert step_dict["timeout-minutes"] == 10
    assert step_dict["env"] == {"PORT": "8000", "CI": "true", "RATIO": "0.5"}

    post_step_dict = policy.ci.steps.post_test[0].to_step_dict()
    assert post_step_dict["with"] == {"fail_ci_if_error": False}
    assert "env" not in post_step_dict

    assert policy.env == {
        "APP_ENV": "staging",
        "PORT": "8080",
        "FEATURE_FLAG": "true",
        "THRESHOLD": "1.25",
    }
    assert policy.linters.is_enabled_for("python") is False
    assert policy.linters.is_enabled_for("go") is True
    assert policy.linters.is_enabled_for("rust") is True

    # [k8s] merged into [kubernetes], with [kubernetes] winning on overlapping leaves
    assert policy.kubernetes.replicas == 5
    assert policy.kubernetes.namespace == "staging-ns"
    assert policy.kubernetes.service_type == "NodePort"
    assert policy.kubernetes.image == "ghcr.io/acme/api:v2"
    assert policy.kubernetes.port == 9000
    assert policy.kubernetes.resources.requests.cpu == "300m"
    assert policy.kubernetes.resources.requests.memory == "256Mi"
    assert policy.kubernetes.resources.limits.cpu == "500m"
    assert policy.kubernetes.liveness_probe.path == "/livez"
    assert policy.kubernetes.readiness_probe.type == "exec"
    assert policy.kubernetes.readiness_probe.command == ["python", "-c", "import sys; sys.exit(0)"]
    assert policy.kubernetes.hpa.enabled is True
    assert policy.kubernetes.hpa.max_replicas == 8

    # StepPolicy rejects missing both uses and run
    with pytest.raises(Exception):
        StepPolicy(name="empty")

    # 3. Resilient leaf-pruning loop isolates invalid leaf fields & unknown sections
    bad_cfg: Dict[str, Any] = {
        "unknown_top_section": {"foo": "bar"},
        "engine": {
            "runner": "ubuntu-24.04",
            "non_destructive": "invalid_bool",
        },
        "ci": {
            "default_branch": "main",
            "runners": {
                "valid-job": "ubuntu-latest",
                "broken-job": "",
            },
            "steps": {
                "pre_test": [
                    {"name": "Valid step", "run": "echo ok", "timeout-minutes": "NaN"},
                    {"name": "Invalid missing action and cmd"},
                ]
            },
        },
        "env": {
            "GOOD_PORT": 3000,
            "BAD_LIST": ["x", "y"],
        },
        "linters": {
            "enabled": True,
            "python": "not_a_bool",
            "go": False,
        },
        "k8s": {
            "replicas": "not_an_int",
            "namespace": "preserved-ns",
            "port": 70000,
        },
        "kubernetes": {
            "service_type": "InvalidServiceType",
            "hpa": {
                "enabled": True,
                "min_replicas": 10,
                "max_replicas": 2,
            },
        },
    }

    pruned_policy, prune_warnings = parse_heurix_policy(bad_cfg)
    assert any("Unknown .heurix.toml section 'unknown_top_section'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'engine.non_destructive'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'ci.runners.broken-job'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'ci.steps.pre_test.0.timeout-minutes'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'ci.steps.pre_test.1'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'env.BAD_LIST'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'linters.python'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'k8s.port'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'kubernetes.service_type'" in w for w in prune_warnings)
    assert any("Warning: Invalid .heurix.toml field 'kubernetes.hpa'" in w for w in prune_warnings)

    # All valid sibling fields survive leaf pruning
    assert pruned_policy.engine.runner == "ubuntu-24.04"
    assert pruned_policy.engine.non_destructive is True
    assert pruned_policy.ci.runners == {"valid-job": "ubuntu-latest"}
    assert len(pruned_policy.ci.steps.pre_test) == 1
    assert pruned_policy.ci.steps.pre_test[0].run == "echo ok"
    assert pruned_policy.ci.steps.pre_test[0].timeout_minutes is None
    assert pruned_policy.env == {"GOOD_PORT": "3000"}
    assert pruned_policy.linters.is_enabled_for("python") is True
    assert pruned_policy.linters.is_enabled_for("go") is False
    assert pruned_policy.kubernetes.namespace == "preserved-ns"
    assert pruned_policy.kubernetes.replicas == 2
    assert pruned_policy.kubernetes.port is None
    assert pruned_policy.kubernetes.service_type == "ClusterIP"
    assert pruned_policy.kubernetes.hpa.enabled is False

    # 4. HeurixPolicy.from_raw() never raises even on None or malformed roots
    assert HeurixPolicy.from_raw(None) == HeurixPolicy()
    assert HeurixPolicy.from_raw("not-a-mapping") == HeurixPolicy()  # type: ignore[arg-type]
    recovered = HeurixPolicy.from_raw(bad_cfg)
    assert recovered.engine.runner == "ubuntu-24.04"
    assert recovered.kubernetes.namespace == "preserved-ns"


def test_policy_linters_global_and_k8s_overlap_fallback():
    from heurix.core.policy import HeurixPolicy, parse_heurix_policy

    # Global linters.enabled = false disables all ecosystems including aliases
    policy, _ = parse_heurix_policy({"linters": {"enabled": False, "python": True}})
    assert policy.linters.is_enabled_for("python") is False
    assert policy.linters.is_enabled_for("cpp") is False
    assert policy.linters.is_enabled_for("c++") is False

    # Overlapping [k8s] valid value survives when [kubernetes] override is invalid
    overlap_cfg = {
        "k8s": {"replicas": 4, "namespace": "fallback-ns"},
        "kubernetes": {"replicas": "bad_int"},
    }
    merged, warnings = parse_heurix_policy(overlap_cfg)
    assert merged.kubernetes.replicas == 4
    assert merged.kubernetes.namespace == "fallback-ns"
    assert any("kubernetes.replicas" in w for w in warnings)

    # Boolean rejected for integer fields like port/replicas
    bool_int_cfg = {"kubernetes": {"replicas": True, "port": False, "namespace": "ok"}}
    clean, bool_warnings = parse_heurix_policy(bool_int_cfg)
    assert clean.kubernetes.replicas == 2
    assert clean.kubernetes.port is None
    assert clean.kubernetes.namespace == "ok"
    assert len(bool_warnings) == 2

    # Mutating raw_cfg is never performed
    original = {"k8s": {"replicas": "bad", "namespace": "stay"}}
    _ = HeurixPolicy.from_raw(original)
    assert original == {"k8s": {"replicas": "bad", "namespace": "stay"}}


def test_policy_applicator_services_linters_env_secrets_ir(tmp_path: Path):
    from heurix.detectors import analyze_repository

    repo = tmp_path / "poly_policy_repo"
    (repo / "services" / "api").mkdir(parents=True)
    (repo / "apps" / "web").mkdir(parents=True)

    # Python FastAPI package with postgres + redis dependencies and ruff lint
    (repo / "services" / "api" / "uv.lock").write_text("", encoding="utf-8")
    (repo / "services" / "api" / "pyproject.toml").write_text(
        """
[project]
name = "api"
requires-python = ">=3.11"
dependencies = ["fastapi", "psycopg2-binary", "redis", "pytest", "ruff"]
""",
        encoding="utf-8",
    )

    # Node Next.js package with mongoose (mongodb) and eslint
    (repo / "apps" / "web" / "package.json").write_text(
        """{
  "name": "@acme/web",
  "scripts": {"build": "next build", "test": "vitest run", "lint": "eslint ."},
  "dependencies": {"next": "^14.0.0", "mongoose": "^8.0.0"}
}""",
        encoding="utf-8",
    )

    # .env.example seeds both safe env vars and secrets (including one later promoted to deploy)
    (repo / ".env.example").write_text(
        """
APP_ENV=development
PROMOTE_TO_DEPLOY=plain_default
MIGRATE_SECRET=from_env_example
DATABASE_URL=postgres://localhost/db
""",
        encoding="utf-8",
    )

    (repo / ".heurix.toml").write_text(
        """
[engine]
runner = "ubuntu-24.04"

[matrix]
python = ["3.11", "3.12"]
node = ["20.x", "22.x"]

[overrides]
python = "3.11"

[services]
exclude = ["postgresql", "Redis"]

[linters]
enabled = true
python = false

[env]
APP_ENV = "staging"
PORT = 8080
DEBUG = true
DATABASE_URL = "postgres://leaked"
API_SECRET = "leaked-secret"
AUTH_TOKEN = "leaked-token"
CUSTOM_SERVICE_ACCOUNT = "{}"
WEBHOOK_ENDPOINT = "https://hooks.example.com"

[secrets]
deploy = ["CUSTOM_DEPLOY_CRED", "MIGRATE_SECRET", "PROMOTE_TO_DEPLOY"]
test = ["UNIT_TEST_SECRET", "VERCEL_TOKEN", "FIREBASE_API_KEY", "AWS_SECRET_ACCESS_KEY", "DOCKER_PASSWORD", "CUSTOM_DEPLOY_CRED"]
""",
        encoding="utf-8",
    )

    ctx = analyze_repository(repo)

    # [engine].runner applied
    assert ctx.runner == "ubuntu-24.04"

    # [matrix] + [overrides] precedence preserved across LanguageContext & MonorepoPackage
    for lang in ctx.get_languages("python"):
        assert lang.runtime_version == "3.11"
        assert lang.matrix_versions == []
        assert lang.lint_cmd is None  # suppressed by [linters].python = false
    for pkg in ctx.monorepo_packages:
        if pkg.language == "python":
            assert pkg.runtime_version == "3.11"
            assert pkg.matrix_versions == []
            assert pkg.lint_cmd is None
        elif pkg.language == "node":
            assert pkg.matrix_versions == ["20.x", "22.x"]
            assert pkg.runtime_version == "22.x"
            assert pkg.lint_cmd is not None  # node linter remains enabled

    # [services].exclude removed postgres (via postgresql alias) and redis (case-insensitive) while keeping mongodb
    remaining_services = {s.name for s in ctx.services}
    assert remaining_services == {"mongodb"}
    assert any("Excluded service 'postgres'" in msg for msg in ctx.explain_log)
    assert any("Excluded service 'redis'" in msg for msg in ctx.explain_log)

    # [env] safe keys applied with scalar coercion; SEC-02 blocked sensitive keys and removed PROMOTE_TO_DEPLOY
    assert ctx.env_vars["APP_ENV"] == "staging"
    assert ctx.env_vars["PORT"] == "8080"
    assert ctx.env_vars["DEBUG"] == "true"
    for blocked in (
        "DATABASE_URL",
        "API_SECRET",
        "AUTH_TOKEN",
        "CUSTOM_SERVICE_ACCOUNT",
        "WEBHOOK_ENDPOINT",
        "PROMOTE_TO_DEPLOY",
    ):
        assert blocked not in ctx.env_vars
    assert any("SEC-02" in msg and "DATABASE_URL" in msg for msg in ctx.explain_log)
    assert any("SEC-02" in msg and "CUSTOM_SERVICE_ACCOUNT" in msg for msg in ctx.explain_log)

    # [secrets] SEC-03 isolation & required_secrets sync
    assert "CUSTOM_DEPLOY_CRED" in ctx.deployment_secrets
    assert "MIGRATE_SECRET" in ctx.deployment_secrets
    assert "PROMOTE_TO_DEPLOY" in ctx.deployment_secrets

    assert "UNIT_TEST_SECRET" in ctx.test_secrets
    assert "DATABASE_URL" in ctx.test_secrets
    for forbidden_test in (
        "MIGRATE_SECRET",
        "PROMOTE_TO_DEPLOY",
        "CUSTOM_DEPLOY_CRED",
        "VERCEL_TOKEN",
        "FIREBASE_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "DOCKER_PASSWORD",
    ):
        assert forbidden_test not in ctx.test_secrets

    assert any("SEC-03" in msg and "VERCEL_TOKEN" in msg for msg in ctx.explain_log)
    assert any("SEC-03" in msg and "CUSTOM_DEPLOY_CRED" in msg for msg in ctx.explain_log)
    assert set(ctx.test_secrets).isdisjoint(set(ctx.deployment_secrets))
    for s in (*ctx.test_secrets, *ctx.deployment_secrets):
        assert s in ctx.required_secrets


def test_context_sync_required_secrets_and_direct_applicator(tmp_path: Path):
    from heurix.core.context import LanguageContext, MonorepoPackage, ProjectContext, ServiceRequirement
    from heurix.core.policy import HeurixPolicy, apply_policy_to_context, parse_heurix_policy
    from heurix.detectors import (
        _LANG_KEY_ALIASES,
        _apply_language_version_policy,
        _normalize_string_list,
        analyze_repository,
    )

    # 1. ProjectContext.sync_required_secrets() works in-place without duplicates
    ctx = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        test_secrets=["EXISTING_TEST"],
        deployment_secrets=["EXISTING_DEPLOY"],
        env_vars={"API_KEY": "should-be-popped", "SAFE_FLAG": "1", "PROMOTE_ME": "val"},
        services=[
            ServiceRequirement(name="mongodb", image="mongo:7"),
            ServiceRequirement(name="postgres", image="postgres:16"),
        ],
        languages=[
            LanguageContext(
                language="go",
                runtime_version="1.22",
                version_source="go.mod",
                package_manager="gomod",
                install_cmd="go mod download",
                lint_cmd="golangci-lint run",
            )
        ],
        monorepo_packages=[
            MonorepoPackage(
                name="svc",
                path="services/svc",
                language="go",
                package_manager="gomod",
                lint_cmd="golangci-lint run",
            )
        ],
    )
    ctx.test_secrets.extend(["NEW_TEST", "EXISTING_TEST"])
    ctx.deployment_secrets.append("NEW_DEPLOY")
    ctx.sync_required_secrets()
    assert ctx.required_secrets == ["EXISTING_TEST", "EXISTING_DEPLOY", "NEW_TEST", "NEW_DEPLOY"]

    # 2. Direct apply_policy_to_context() enforces mongo alias, global linters=false, SEC-02 pop, SEC-03, single-entry matrix.os
    raw_cfg = {
        "engine": {"runner": "ubuntu-22.04"},
        "matrix": {"os": ["ubuntu-24.04"]},
        "services": {"exclude": ["mongo"]},
        "linters": {"enabled": False},
        "env": {"API_KEY": "secret", "APP_PORT": 9000},
        "secrets": {"deploy": ["PROMOTE_ME", "NEW_TEST"], "test": ["EXTRA_TEST", "DOCKER_TOKEN"]},
    }
    policy, warnings = parse_heurix_policy(raw_cfg)
    assert warnings == []
    apply_policy_to_context(ctx, policy, raw_config=raw_cfg)

    # Single-entry [matrix].os overrides [engine].runner
    assert ctx.matrix_os == []
    assert ctx.runner == "ubuntu-24.04"
    assert [s.name for s in ctx.services] == ["postgres"]
    assert ctx.languages[0].lint_cmd is None
    assert ctx.monorepo_packages[0].lint_cmd is None
    assert ctx.env_vars == {"SAFE_FLAG": "1", "APP_PORT": "9000"}
    assert "NEW_TEST" in ctx.deployment_secrets
    assert "NEW_TEST" not in ctx.test_secrets
    assert "EXTRA_TEST" in ctx.test_secrets
    assert "DOCKER_TOKEN" not in ctx.test_secrets
    assert "EXTRA_TEST" in ctx.required_secrets

    # 3. Partial invalid .heurix.toml in analyze_repository() keeps valid policies & logs warnings
    repo = tmp_path / "partial_bad_toml"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["redis"]\n',
        encoding="utf-8",
    )
    (repo / ".heurix.toml").write_text(
        """
[engine]
runner = "ubuntu-24.04"

[services]
exclude = ["redis"]

[kubernetes]
replicas = "not_a_number"
namespace = "prod"
""",
        encoding="utf-8",
    )
    analyzed = analyze_repository(repo)
    assert analyzed.runner == "ubuntu-24.04"
    assert analyzed.services == []
    assert any("Invalid .heurix.toml field 'kubernetes.replicas'" in w for w in analyzed.explain_log)
    assert HeurixPolicy.from_raw(analyzed.policy_config).kubernetes.namespace == "prod"

    # 4. Backward compatibility exports remain on heurix.detectors
    assert "python-version" in _LANG_KEY_ALIASES
    assert _normalize_string_list(["3.11", 3.12, True]) == ["3.11", "3.12"]
    assert callable(_apply_language_version_policy)
