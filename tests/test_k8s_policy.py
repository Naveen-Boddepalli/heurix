"""
Tests for template-decoupled Kubernetes synthesis, framework profiles, [kubernetes]/[k8s] policy overrides,
and repo-local .heurix/templates/k8s/ overrides.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from heurix.core.context import ContainerContext, LanguageContext, ProjectContext
from heurix.core.policy import K8sProbePolicy
from heurix.core.validator import PreflightValidator
from heurix.synthesizers.kubernetes import (
    K8S_FRAMEWORK_PROFILES,
    K8sProfile,
    KubernetesSynthesizer,
    SENSITIVE_KEYWORDS,
    _is_sensitive_env_key,
    _resolve_probe,
)


def _python_lang(framework: str | None = None) -> LanguageContext:
    return LanguageContext(
        language="python",
        runtime_version="3.12",
        version_source=".python-version",
        package_manager="uv",
        install_cmd="uv sync --frozen",
        framework=framework,
    )


def _node_lang(framework: str | None = None) -> LanguageContext:
    return LanguageContext(
        language="node",
        runtime_version="20.x",
        version_source="package.json",
        package_manager="npm",
        install_cmd="npm ci",
        framework=framework,
    )


def _go_lang(framework: str | None = None) -> LanguageContext:
    return LanguageContext(
        language="go",
        runtime_version="1.22",
        version_source="go.mod",
        package_manager="gomod",
        install_cmd="go mod download",
        framework=framework,
    )


def _rust_lang(framework: str | None = None) -> LanguageContext:
    return LanguageContext(
        language="rust",
        runtime_version="stable",
        version_source="Cargo.toml",
        package_manager="cargo",
        install_cmd="cargo fetch",
        framework=framework,
    )


def test_k8s_template_framework_profiles():
    yaml = YAML(typ="safe")
    syn = KubernetesSynthesizer()

    # Backward-compatibility exports & registry structure
    assert isinstance(K8S_FRAMEWORK_PROFILES["FastAPI"], K8sProfile)
    assert "SECRET" in SENSITIVE_KEYWORDS
    assert _is_sensitive_env_key("DATABASE_URL") is True
    assert _is_sensitive_env_key("APP_PORT") is False

    # 1. FastAPI: port 8000, httpGet /health, Python resource baseline
    fastapi_res = syn.synthesize(
        ProjectContext(
            repo_name="fastapi_svc",
            repo_root="/demo",
            languages=[_python_lang("FastAPI")],
            containers=[ContainerContext(dockerfile_path="Dockerfile")],
        )
    )
    for manifest_yaml in fastapi_res.values():
        assert manifest_yaml.startswith("# Synthesized deterministically by Heurix (hx)\n")
    dep = yaml.load(fastapi_res["k8s/deployment.yaml"])
    container = dep["spec"]["template"]["spec"]["containers"][0]
    assert container["ports"] == [{"containerPort": 8000}]
    assert container["livenessProbe"]["httpGet"] == {"path": "/health", "port": 8000}
    assert container["readinessProbe"]["httpGet"] == {"path": "/health", "port": 8000}
    assert container["resources"] == {
        "requests": {"cpu": "100m", "memory": "256Mi"},
        "limits": {"cpu": "500m", "memory": "512Mi"},
    }
    assert "namespace" not in dep["metadata"]

    # 2. Streamlit: port 8501 beats Dockerfile exposed port, httpGet /_stcore/health
    streamlit_res = syn.synthesize(
        ProjectContext(
            repo_name="dash_app",
            repo_root="/demo",
            languages=[_python_lang("Streamlit")],
            containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
            env_vars={
                "PORT": "8000",
                "STREAMLIT_SERVER_HEADLESS": "true",
                "FEATURE_FLAG": "false",
                "POLICY_SECRET_TOKEN": "should-redact",
            },
            policy_config={
                "env": {
                    "CUSTOM_PORT": 8080,
                    "DEBUG": False,
                    "API_KEY": "blocked",
                    "TEST_PASS_THROUGH": "ok",
                },
                "secrets": {
                    "test": ["TEST_PASS_THROUGH"],
                    "deploy": ["DEPLOY_CRED"],
                },
            },
        )
    )
    st_dep = yaml.load(streamlit_res["k8s/deployment.yaml"])
    st_container = st_dep["spec"]["template"]["spec"]["containers"][0]
    assert st_container["ports"] == [{"containerPort": 8501}]
    assert st_container["livenessProbe"]["httpGet"] == {"path": "/_stcore/health", "port": 8501}
    assert st_container["readinessProbe"]["httpGet"] == {"path": "/_stcore/health", "port": 8501}
    assert "k8s/configmap.yaml" in streamlit_res
    cm_raw = streamlit_res["k8s/configmap.yaml"]
    assert "PORT: '8000'" in cm_raw or 'PORT: "8000"' in cm_raw
    assert "STREAMLIT_SERVER_HEADLESS: 'true'" in cm_raw or 'STREAMLIT_SERVER_HEADLESS: "true"' in cm_raw
    cm_doc = yaml.load(cm_raw)
    assert cm_doc["data"]["PORT"] == "8000"
    assert isinstance(cm_doc["data"]["PORT"], str)
    assert cm_doc["data"]["STREAMLIT_SERVER_HEADLESS"] == "true"
    assert isinstance(cm_doc["data"]["STREAMLIT_SERVER_HEADLESS"], str)
    assert cm_doc["data"]["FEATURE_FLAG"] == "false"
    assert cm_doc["data"]["CUSTOM_PORT"] == "8080"
    assert cm_doc["data"]["DEBUG"] == "false"
    assert "POLICY_SECRET_TOKEN" not in cm_doc["data"]
    assert "API_KEY" not in cm_doc["data"]
    assert "TEST_PASS_THROUGH" not in cm_doc["data"]

    # 3. Next.js / Nuxt / Remix / SvelteKit -> 3000 httpGet /; Astro -> 4321 httpGet /
    for fw, expected_port in (
        ("Next.js", 3000),
        ("Nuxt", 3000),
        ("Remix", 3000),
        ("SvelteKit", 3000),
        ("Astro", 4321),
    ):
        res = syn.synthesize(
            ProjectContext(
                repo_name="web_app",
                repo_root="/demo",
                languages=[_node_lang(fw)],
            )
        )
        c = yaml.load(res["k8s/deployment.yaml"])["spec"]["template"]["spec"]["containers"][0]
        assert c["ports"] == [{"containerPort": expected_port}]
        assert c["livenessProbe"]["httpGet"] == {"path": "/", "port": expected_port}
        assert c["readinessProbe"]["httpGet"] == {"path": "/", "port": expected_port}

    # 4. Express / NestJS / Django / Flask -> tcpSocket
    for lang_ctx, expected_port in (
        (_node_lang("Express"), 3000),
        (_node_lang("NestJS"), 3000),
        (_python_lang("Django"), 8000),
        (_python_lang("Flask"), 5000),
    ):
        res = syn.synthesize(
            ProjectContext(
                repo_name="backend_svc",
                repo_root="/demo",
                languages=[lang_ctx],
            )
        )
        c = yaml.load(res["k8s/deployment.yaml"])["spec"]["template"]["spec"]["containers"][0]
        assert c["ports"] == [{"containerPort": expected_port}]
        assert c["livenessProbe"]["tcpSocket"] == {"port": expected_port}
        assert c["readinessProbe"]["tcpSocket"] == {"port": expected_port}

    # 5. Go (Gin/Echo/Fiber) and Rust (Actix-Web/Axum/Rocket) lightweight baselines
    for lang_ctx, expected_port in (
        (_go_lang("Gin"), 8080),
        (_go_lang("Echo"), 8080),
        (_go_lang("Fiber"), 8080),
        (_rust_lang("Actix-Web"), 8080),
        (_rust_lang("Axum"), 8000),
        (_rust_lang("Rocket"), 8000),
    ):
        res = syn.synthesize(
            ProjectContext(
                repo_name="fast_svc",
                repo_root="/demo",
                languages=[lang_ctx],
            )
        )
        c = yaml.load(res["k8s/deployment.yaml"])["spec"]["template"]["spec"]["containers"][0]
        assert c["ports"] == [{"containerPort": expected_port}]
        assert c["livenessProbe"]["tcpSocket"] == {"port": expected_port}
        assert c["resources"] == {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": "500m", "memory": "256Mi"},
        }

    # 6. Generic Go baseline with Dockerfile exposed_ports override over 8080 & Kind multiline patch check
    go_docker_res = syn.synthesize(
        ProjectContext(
            repo_name="bare_go",
            repo_root="/demo",
            languages=[_go_lang(None)],
            containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[9090])],
        )
    )
    go_c = yaml.load(go_docker_res["k8s/deployment.yaml"])["spec"]["template"]["spec"]["containers"][0]
    assert go_c["ports"] == [{"containerPort": 9090}]
    assert go_c["resources"] == {
        "requests": {"cpu": "50m", "memory": "64Mi"},
        "limits": {"cpu": "500m", "memory": "256Mi"},
    }
    kind_doc = yaml.load(go_docker_res["k8s/kind-config.yaml"])
    patches = kind_doc["nodes"][0]["kubeadmConfigPatches"]
    assert isinstance(patches, list) and len(patches) == 1
    assert "ingress-ready=true" in patches[0]


def test_k8s_policy_overrides_probes_resources_and_hpa():
    yaml = YAML(typ="safe")
    syn = KubernetesSynthesizer()

    # 1. Inactive without containers/framework/explicit [kubernetes], even with [engine]/[ci]
    assert (
        syn.synthesize(
            ProjectContext(
                repo_name="no_k8s",
                repo_root="/demo",
                languages=[_python_lang(None)],
                policy_config={"engine": {"runner": "ubuntu-24.04"}, "ci": {"include_k8s": True}},
            )
        )
        == {}
    )

    # 2. [kubernetes] overrides across Deployment, Service, Ingress, ConfigMap, and HPA
    ctx = ProjectContext(
        repo_name="prod_service",
        repo_root="/demo",
        languages=[_python_lang("FastAPI")],
        containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
        env_vars={"APP_ENV": "production", "WORKERS": "4"},
        policy_config={
            "kubernetes": {
                "replicas": 5,
                "namespace": "prod-api",
                "image": "ghcr.io/org/app:v2",
                "port": 9090,
                "service_type": "LoadBalancer",
                "resources": {
                    "requests": {"cpu": "250m", "memory": "512Mi"},
                    "limits": {"cpu": "1000m", "memory": "1Gi"},
                },
                "liveness_probe": {
                    "enabled": True,
                    "type": "httpGet",
                    "path": "/livez",
                    "initial_delay_seconds": 0,
                    "period_seconds": 20,
                    "timeout_seconds": 3,
                    "failure_threshold": 5,
                },
                "readiness_probe": {
                    "enabled": True,
                    "command": ["python", "-c", "import sys; sys.exit(0)"],
                    "initial_delay_seconds": 4,
                    "period_seconds": 8,
                },
                "hpa": {
                    "enabled": True,
                    "min_replicas": 3,
                    "max_replicas": 12,
                    "target_cpu_utilization": 70,
                },
            }
        },
    )

    res = syn.synthesize(ctx)
    assert set(res.keys()) == {
        "k8s/deployment.yaml",
        "k8s/service.yaml",
        "k8s/ingress.yaml",
        "k8s/kind-config.yaml",
        "k8s/configmap.yaml",
        "k8s/hpa.yaml",
    }

    dep = yaml.load(res["k8s/deployment.yaml"])
    assert dep["metadata"]["namespace"] == "prod-api"
    assert dep["spec"]["replicas"] == 5
    container = dep["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "ghcr.io/org/app:v2"
    assert container["ports"] == [{"containerPort": 9090}]
    assert container["resources"] == {
        "requests": {"cpu": "250m", "memory": "512Mi"},
        "limits": {"cpu": "1000m", "memory": "1Gi"},
    }
    assert container["livenessProbe"] == {
        "httpGet": {"path": "/livez", "port": 9090},
        "initialDelaySeconds": 0,
        "periodSeconds": 20,
        "timeoutSeconds": 3,
        "failureThreshold": 5,
    }
    assert container["readinessProbe"] == {
        "exec": {"command": ["python", "-c", "import sys; sys.exit(0)"]},
        "initialDelaySeconds": 4,
        "periodSeconds": 8,
    }

    svc = yaml.load(res["k8s/service.yaml"])
    assert svc["metadata"]["namespace"] == "prod-api"
    assert svc["spec"]["type"] == "LoadBalancer"
    assert svc["spec"]["ports"] == [{"protocol": "TCP", "port": 80, "targetPort": 9090}]

    ing = yaml.load(res["k8s/ingress.yaml"])
    assert ing["metadata"]["namespace"] == "prod-api"

    cm = yaml.load(res["k8s/configmap.yaml"])
    assert cm["metadata"]["namespace"] == "prod-api"
    assert cm["data"] == {"APP_ENV": "production", "WORKERS": "4"}

    kind = yaml.load(res["k8s/kind-config.yaml"])
    assert "namespace" not in kind["metadata"]

    hpa = yaml.load(res["k8s/hpa.yaml"])
    assert res["k8s/hpa.yaml"].startswith("# Synthesized deterministically by Heurix (hx)\n")
    assert hpa["apiVersion"] == "autoscaling/v2"
    assert hpa["kind"] == "HorizontalPodAutoscaler"
    assert hpa["metadata"]["name"] == "prod-service-hpa"
    assert hpa["metadata"]["namespace"] == "prod-api"
    assert hpa["spec"] == {
        "scaleTargetRef": {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "name": "prod-service",
        },
        "minReplicas": 3,
        "maxReplicas": 12,
        "metrics": [
            {
                "type": "Resource",
                "resource": {
                    "name": "cpu",
                    "target": {
                        "type": "Utilization",
                        "averageUtilization": 70,
                    },
                },
            }
        ],
    }

    # 3. [k8s] alias + disabled probes + inferred httpGet path + empty exec fallback warning + no-container activation
    alias_ctx = ProjectContext(
        repo_name="alias_app",
        repo_root="/demo",
        languages=[_python_lang("FastAPI")],
        policy_config={
            "k8s": {
                "service_type": "NodePort",
                "resources": {"requests": {"cpu": "200m"}},
                "liveness_probe": {"enabled": False},
                "readiness_probe": {"type": "exec", "command": []},
            }
        },
    )
    alias_res = syn.synthesize(alias_ctx)
    assert "k8s/hpa.yaml" not in alias_res
    alias_dep = yaml.load(alias_res["k8s/deployment.yaml"])
    alias_c = alias_dep["spec"]["template"]["spec"]["containers"][0]
    assert "livenessProbe" not in alias_c
    # Invalid empty exec falls back to FastAPI default httpGet /health with warning
    assert alias_c["readinessProbe"] == {
        "httpGet": {"path": "/health", "port": 8000},
        "initialDelaySeconds": 5,
        "periodSeconds": 10,
    }
    assert any("exec" in msg.lower() for msg in alias_ctx.explain_log)
    assert alias_c["resources"] == {
        "requests": {"cpu": "200m", "memory": "256Mi"},
        "limits": {"cpu": "500m", "memory": "512Mi"},
    }
    alias_svc = yaml.load(alias_res["k8s/service.yaml"])
    assert alias_svc["spec"]["type"] == "NodePort"

    # 4. Synthesis activates via explicit [k8s] even with no containers and no frameworks
    explicit_ctx = ProjectContext(
        repo_name="custom_k8s_only",
        repo_root="/demo",
        policy_config={
            "k8s": {
                "port": 7070,
                "readiness_probe": {"path": "/readyz", "port": 7071},
                "liveness_probe": {"type": "tcpSocket"},
            }
        },
    )
    explicit_res = syn.synthesize(explicit_ctx)
    assert "k8s/deployment.yaml" in explicit_res
    ex_c = yaml.load(explicit_res["k8s/deployment.yaml"])["spec"]["template"]["spec"]["containers"][0]
    assert ex_c["ports"] == [{"containerPort": 7070}]
    assert ex_c["readinessProbe"]["httpGet"] == {"path": "/readyz", "port": 7071}
    assert ex_c["livenessProbe"]["tcpSocket"] == {"port": 7070}

    # 5. Direct _resolve_probe unit checks
    profile = K8S_FRAMEWORK_PROFILES["FastAPI"]
    probe_ctx = ProjectContext(repo_name="probe_check", repo_root="/demo")
    assert _resolve_probe(profile.liveness_probe, K8sProbePolicy(enabled=False), 8000, probe_ctx) is None
    inferred_http = _resolve_probe(profile.readiness_probe, K8sProbePolicy(path="/ready"), 8080, probe_ctx)
    assert inferred_http == {
        "httpGet": {"path": "/ready", "port": 8080},
        "initialDelaySeconds": 5,
        "periodSeconds": 10,
    }


def test_k8s_local_override_and_preflight_validation(tmp_path: Path):
    yaml = YAML(typ="safe")
    syn = KubernetesSynthesizer()
    validator = PreflightValidator()

    # 1. Validate every synthesized K8s manifest across FastAPI, Streamlit, Go/Gin, Rust/Axum, and HPA configs
    scenarios = [
        ProjectContext(
            repo_name="fastapi_app",
            repo_root="/demo",
            languages=[_python_lang("FastAPI")],
            containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
        ),
        ProjectContext(
            repo_name="streamlit_app",
            repo_root="/demo",
            languages=[_python_lang("Streamlit")],
            containers=[ContainerContext(dockerfile_path="Dockerfile")],
            env_vars={"PORT": "8501", "STREAMLIT_SERVER_HEADLESS": "true"},
            required_secrets=["API_KEY"],
        ),
        ProjectContext(
            repo_name="go_gin_app",
            repo_root="/demo",
            languages=[_go_lang("Gin")],
            containers=[ContainerContext(dockerfile_path="Dockerfile")],
        ),
        ProjectContext(
            repo_name="rust_axum_app",
            repo_root="/demo",
            languages=[_rust_lang("Axum")],
            containers=[ContainerContext(dockerfile_path="Dockerfile")],
        ),
        ProjectContext(
            repo_name="hpa_app",
            repo_root="/demo",
            languages=[_python_lang("FastAPI")],
            containers=[ContainerContext(dockerfile_path="Dockerfile")],
            env_vars={"APP_ENV": "production"},
            policy_config={
                "kubernetes": {
                    "replicas": 3,
                    "namespace": "apps",
                    "liveness_probe": {"enabled": False},
                    "readiness_probe": {"type": "exec", "command": ["echo", "ok"]},
                    "hpa": {
                        "enabled": True,
                        "min_replicas": 2,
                        "max_replicas": 6,
                        "target_cpu_utilization": 75,
                    },
                }
            },
        ),
    ]

    for ctx in scenarios:
        rendered = syn.synthesize(ctx)
        assert rendered
        for rel_path, content in rendered.items():
            is_valid, errors = validator.validate(rel_path, content)
            assert is_valid, f"Validation failed for {ctx.repo_name}/{rel_path}: {errors}"

    # 2. Custom .heurix/templates/k8s/hpa.yaml.j2 override via ChoiceLoader while siblings fall back to bundled templates
    repo = tmp_path / "override_repo"
    k8s_override_dir = repo / ".heurix" / "templates" / "k8s"
    k8s_override_dir.mkdir(parents=True)
    (k8s_override_dir / "hpa.yaml.j2").write_text(
        """# Synthesized deterministically by Heurix (hx)
# Custom local HPA override
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ hpa_name | yaml_scalar }}
{% if namespace %}
  namespace: {{ namespace | yaml_scalar }}
{% endif %}
  annotations:
    heurix.io/override: "true"
spec:
  scaleTargetRef:
    apiVersion: {{ scale_target_ref.apiVersion | yaml_scalar }}
    kind: {{ scale_target_ref.kind | yaml_scalar }}
    name: {{ scale_target_ref.name | yaml_scalar }}
  minReplicas: {{ min_replicas }}
  maxReplicas: {{ max_replicas }}
  metrics:
{{ metrics | yaml_block(indent=4) }}
""",
        encoding="utf-8",
    )

    override_ctx = ProjectContext(
        repo_name="local_override_app",
        repo_root=str(repo),
        languages=[_python_lang("FastAPI")],
        containers=[ContainerContext(dockerfile_path="Dockerfile")],
        policy_config={
            "kubernetes": {
                "namespace": "team-a",
                "hpa": {"enabled": True, "min_replicas": 2, "max_replicas": 5, "target_cpu_utilization": 65},
            }
        },
    )
    override_res = syn.synthesize(override_ctx)
    assert "k8s/hpa.yaml" in override_res
    hpa_doc = yaml.load(override_res["k8s/hpa.yaml"])
    assert hpa_doc["metadata"]["annotations"]["heurix.io/override"] == "true"
    assert hpa_doc["metadata"]["namespace"] == "team-a"
    # Sibling manifests fell back to bundled templates cleanly
    dep_doc = yaml.load(override_res["k8s/deployment.yaml"])
    svc_doc = yaml.load(override_res["k8s/service.yaml"])
    assert dep_doc["kind"] == "Deployment"
    assert svc_doc["kind"] == "Service"
    for rel_path, content in override_res.items():
        is_valid, errors = validator.validate(rel_path, content)
        assert is_valid, f"Override validation failed for {rel_path}: {errors}"

    # 3. Traversal / symlink escape inside .heurix/templates/k8s/ raises Path traversal security violation
    outside_template = tmp_path / "outside_hpa.yaml.j2"
    outside_template.write_text("kind: Evil\n", encoding="utf-8")
    symlink_repo = tmp_path / "symlink_escape_repo"
    symlink_k8s_dir = symlink_repo / ".heurix" / "templates" / "k8s"
    symlink_k8s_dir.mkdir(parents=True)
    (symlink_k8s_dir / "hpa.yaml.j2").symlink_to(outside_template)

    escape_ctx = ProjectContext(
        repo_name="escape_app",
        repo_root=str(symlink_repo),
        languages=[_python_lang("FastAPI")],
        policy_config={"kubernetes": {"hpa": {"enabled": True}}},
    )
    with pytest.raises(ValueError, match="Path traversal security violation"):
        syn.synthesize(escape_ctx)

    traversal_ctx = ProjectContext(
        repo_name="traversal_app",
        repo_root=str(repo),
        languages=[_python_lang("FastAPI")],
        policy_config={"engine": {"templates_dir": "../outside"}},
    )
    with pytest.raises(ValueError, match="Path traversal security violation"):
        syn.synthesize(traversal_ctx)
