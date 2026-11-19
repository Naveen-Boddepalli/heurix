"""
Kubernetes Manifest Synthesizer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from heurix.core.context import LanguageContext, ProjectContext
from heurix.core.policy import (
    HeurixPolicy,
    K8sProbePolicy,
    is_deployment_secret_key,
    is_sensitive_env_key,
    is_valid_image_tag,
)
from heurix.synthesizers.base import BaseSynthesizer
from heurix.synthesizers.templating import render_yaml_template


def _is_sensitive_env_key(key: str) -> bool:
    """Return True if an environment variable key matches any sensitive credential keyword."""
    return is_sensitive_env_key(key)


@dataclass(frozen=True)
class K8sProbeSpec:
    """Default probe specification for a Kubernetes framework or language profile."""

    type: str = "tcpSocket"
    path: str | None = None
    port: int | None = None
    command: tuple[str, ...] | None = None
    initial_delay_seconds: int = 15
    period_seconds: int = 10
    timeout_seconds: int | None = None
    failure_threshold: int | None = None


@dataclass(frozen=True)
class K8sProfile:
    """Default port, resource sizing, and probe settings for a framework/runtime."""

    port: int = 8080
    cpu_request: str = "100m"
    memory_request: str = "256Mi"
    cpu_limit: str = "500m"
    memory_limit: str = "512Mi"
    liveness_probe: K8sProbeSpec = field(
        default_factory=lambda: K8sProbeSpec(
            type="tcpSocket",
            initial_delay_seconds=15,
            period_seconds=10,
        )
    )
    readiness_probe: K8sProbeSpec = field(
        default_factory=lambda: K8sProbeSpec(
            type="tcpSocket",
            initial_delay_seconds=5,
            period_seconds=10,
        )
    )


def _http_profile(
    port: int,
    path: str,
    *,
    cpu_request: str = "100m",
    memory_request: str = "256Mi",
    cpu_limit: str = "500m",
    memory_limit: str = "512Mi",
) -> K8sProfile:
    return K8sProfile(
        port=port,
        cpu_request=cpu_request,
        memory_request=memory_request,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        liveness_probe=K8sProbeSpec(
            type="httpGet",
            path=path,
            initial_delay_seconds=15,
            period_seconds=10,
        ),
        readiness_probe=K8sProbeSpec(
            type="httpGet",
            path=path,
            initial_delay_seconds=5,
            period_seconds=10,
        ),
    )


def _tcp_profile(
    port: int,
    *,
    cpu_request: str = "100m",
    memory_request: str = "256Mi",
    cpu_limit: str = "500m",
    memory_limit: str = "512Mi",
) -> K8sProfile:
    return K8sProfile(
        port=port,
        cpu_request=cpu_request,
        memory_request=memory_request,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        liveness_probe=K8sProbeSpec(
            type="tcpSocket",
            initial_delay_seconds=15,
            period_seconds=10,
        ),
        readiness_probe=K8sProbeSpec(
            type="tcpSocket",
            initial_delay_seconds=5,
            period_seconds=10,
        ),
    )


K8S_FRAMEWORK_PROFILES: dict[str, K8sProfile] = {
    "Streamlit": _http_profile(8501, "/_stcore/health"),
    "FastAPI": _http_profile(8000, "/health"),
    "Next.js": _http_profile(3000, "/"),
    "Nuxt": _http_profile(3000, "/"),
    "Remix": _http_profile(3000, "/"),
    "SvelteKit": _http_profile(3000, "/"),
    "Astro": _http_profile(4321, "/"),
    "Express": _tcp_profile(3000),
    "NestJS": _tcp_profile(3000),
    "Django": _tcp_profile(8000),
    "Flask": _tcp_profile(5000),
    "Gin": _tcp_profile(8080, cpu_request="50m", memory_request="64Mi", memory_limit="256Mi"),
    "Echo": _tcp_profile(8080, cpu_request="50m", memory_request="64Mi", memory_limit="256Mi"),
    "Fiber": _tcp_profile(8080, cpu_request="50m", memory_request="64Mi", memory_limit="256Mi"),
    "Actix-Web": _tcp_profile(8080, cpu_request="50m", memory_request="64Mi", memory_limit="256Mi"),
    "Axum": _tcp_profile(8000, cpu_request="50m", memory_request="64Mi", memory_limit="256Mi"),
    "Rocket": _tcp_profile(8000, cpu_request="50m", memory_request="64Mi", memory_limit="256Mi"),
}

_K8S_FRAMEWORK_INDEX: dict[str, K8sProfile] = {
    key.lower(): val for key, val in K8S_FRAMEWORK_PROFILES.items()
}

_GO_RUST_BASELINE = _tcp_profile(
    8080,
    cpu_request="50m",
    memory_request="64Mi",
    cpu_limit="500m",
    memory_limit="256Mi",
)

_DEFAULT_BASELINE = _tcp_profile(
    8080,
    cpu_request="100m",
    memory_request="256Mi",
    cpu_limit="500m",
    memory_limit="512Mi",
)


def _resolve_language_baseline(language: str | None) -> K8sProfile:
    """Resolve default Kubernetes resource/probe profile for a language runtime."""
    if language and language.strip().lower() in {"go", "rust"}:
        return _GO_RUST_BASELINE
    return _DEFAULT_BASELINE


def _resolve_k8s_profile(primary: LanguageContext | None) -> K8sProfile:
    """Select the framework profile if recognized, else fall back to language baseline."""
    if primary is not None:
        if primary.framework:
            fw_profile = _K8S_FRAMEWORK_INDEX.get(primary.framework.strip().lower())
            if fw_profile is not None:
                return fw_profile
        return _resolve_language_baseline(primary.language)
    return _DEFAULT_BASELINE


def _build_default_probe(spec: K8sProbeSpec, port: int) -> dict[str, Any]:
    probe_port = spec.port if spec.port is not None else port
    probe: dict[str, Any] = {}
    if spec.type == "httpGet":
        probe["httpGet"] = {"path": spec.path or "/", "port": probe_port}
    elif spec.type == "exec" and spec.command:
        probe["exec"] = {"command": list(spec.command)}
    else:
        probe["tcpSocket"] = {"port": probe_port}
    probe["initialDelaySeconds"] = spec.initial_delay_seconds
    probe["periodSeconds"] = spec.period_seconds
    if spec.timeout_seconds is not None:
        probe["timeoutSeconds"] = spec.timeout_seconds
    if spec.failure_threshold is not None:
        probe["failureThreshold"] = spec.failure_threshold
    return probe


def _resolve_probe(
    profile_probe: K8sProbeSpec,
    policy_probe: K8sProbePolicy,
    resolved_port: int,
    context: ProjectContext,
    probe_name: str = "probe",
) -> dict[str, Any] | None:
    """
    Resolve a Kubernetes probe dictionary from framework defaults and policy overrides.

    Returns None when disabled (`enabled = False`). Invalid empty `exec` commands
    log a non-fatal explain warning and fall back to the profile default probe.
    """
    if policy_probe.enabled is False:
        return None

    probe_type: str
    if policy_probe.type is not None:
        probe_type = policy_probe.type
    elif policy_probe.path is not None:
        probe_type = "httpGet"
    elif policy_probe.command is not None:
        probe_type = "exec"
    else:
        probe_type = profile_probe.type

    probe_port = (
        policy_probe.port
        if policy_probe.port is not None
        else (profile_probe.port if profile_probe.port is not None else resolved_port)
    )
    initial_delay = (
        policy_probe.initial_delay_seconds
        if policy_probe.initial_delay_seconds is not None
        else profile_probe.initial_delay_seconds
    )
    period = (
        policy_probe.period_seconds
        if policy_probe.period_seconds is not None
        else profile_probe.period_seconds
    )
    timeout = (
        policy_probe.timeout_seconds
        if policy_probe.timeout_seconds is not None
        else profile_probe.timeout_seconds
    )
    failure_threshold = (
        policy_probe.failure_threshold
        if policy_probe.failure_threshold is not None
        else profile_probe.failure_threshold
    )

    if probe_type == "exec":
        cmd = (
            list(policy_probe.command)
            if policy_probe.command is not None
            else (list(profile_probe.command) if profile_probe.command else [])
        )
        if not cmd or all(not str(part).strip() for part in cmd):
            context.add_explain(
                f"Warning: Ignoring invalid empty exec command for Kubernetes {probe_name}; falling back to profile default."
            )
            return _build_default_probe(profile_probe, resolved_port)
        handler: dict[str, Any] = {"exec": {"command": [str(part) for part in cmd]}}
    elif probe_type == "httpGet":
        probe_path = policy_probe.path or profile_probe.path or "/"
        handler = {"httpGet": {"path": probe_path, "port": probe_port}}
    else:
        handler = {"tcpSocket": {"port": probe_port}}

    probe: dict[str, Any] = dict(handler)
    probe["initialDelaySeconds"] = initial_delay
    probe["periodSeconds"] = period
    if timeout is not None:
        probe["timeoutSeconds"] = timeout
    if failure_threshold is not None:
        probe["failureThreshold"] = failure_threshold
    return probe


class KubernetesSynthesizer(BaseSynthesizer):
    @property
    def name(self) -> str:
        return "Kubernetes Manifests"

    def synthesize(self, context: ProjectContext) -> dict[str, str]:
        raw_cfg = context.policy_config if isinstance(context.policy_config, Mapping) else {}
        policy = HeurixPolicy.from_raw(raw_cfg)
        k8s_policy = policy.kubernetes

        has_explicit_k8s_policy = (
            "kubernetes" in policy.model_fields_set
            or (isinstance(raw_cfg.get("kubernetes"), Mapping) and len(raw_cfg["kubernetes"]) > 0)
            or (isinstance(raw_cfg.get("k8s"), Mapping) and len(raw_cfg["k8s"]) > 0)
        )
        # Manifests deploy an image, so without a Dockerfile (or an explicit
        # [kubernetes] policy naming one) they would reference an image that
        # nothing builds.
        if not context.containers and not has_explicit_k8s_policy:
            return {}

        app_name = context.repo_name.lower().replace("_", "-")
        primary = context.get_primary_language()
        profile = _resolve_k8s_profile(primary)
        is_streamlit = bool(
            primary and primary.framework and primary.framework.strip().lower() == "streamlit"
        )

        dockerfile_port = next(
            (c.exposed_ports[0] for c in context.containers if c.exposed_ports),
            None,
        )
        if k8s_policy.port is not None:
            port = k8s_policy.port
        elif is_streamlit:
            port = 8501
        elif dockerfile_port is not None:
            port = dockerfile_port
        else:
            port = profile.port

        cpu_req = k8s_policy.resources.requests.cpu or profile.cpu_request
        mem_req = k8s_policy.resources.requests.memory or profile.memory_request
        cpu_limit = k8s_policy.resources.limits.cpu or profile.cpu_limit
        mem_limit = k8s_policy.resources.limits.memory or profile.memory_limit

        liveness_probe = _resolve_probe(
            profile.liveness_probe,
            k8s_policy.liveness_probe,
            port,
            context,
            probe_name="liveness_probe",
        )
        readiness_probe = _resolve_probe(
            profile.readiness_probe,
            k8s_policy.readiness_probe,
            port,
            context,
            probe_name="readiness_probe",
        )

        # Deploy credentials (VERCEL_TOKEN, FIREBASE_*) belong to CI deploy jobs only;
        # mounting them into the running app's pod would leak them at runtime.
        deploy_only = set(context.deployment_secrets) | {
            s.strip() for s in policy.secrets.deploy if isinstance(s, str) and s.strip()
        }
        declared_secrets = {
            key
            for key in (
                set(context.required_secrets)
                | set(context.test_secrets)
                | {s.strip() for s in policy.secrets.test if isinstance(s, str) and s.strip()}
            )
            if key not in deploy_only and not is_deployment_secret_key(key)
        }

        merged_env: dict[str, str] = {}
        for k, v in context.env_vars.items():
            merged_env[str(k)] = str(v)
        for k, v in policy.env.items():
            merged_env[str(k)] = str(v)

        safe_env = {
            k: str(v)
            for k, v in sorted(merged_env.items())
            if k not in declared_secrets and not is_sensitive_env_key(k)
        }

        env_from: list[dict[str, Any]] = []
        if safe_env:
            env_from.append({"configMapRef": {"name": f"{app_name}-config"}})
        if declared_secrets:
            env_from.append(
                {
                    "secretRef": {
                        "name": f"{app_name}-secrets",
                        "optional": True,
                    }
                }
            )

        # Env-derived tags come from scanned .env files and may be placeholders
        # (e.g. "${GIT_SHA}"); only accept syntactically valid tags.
        raw_tag = k8s_policy.image_tag or next(
            (
                tag
                for tag in (
                    str(context.env_vars.get("IMAGE_TAG") or "").strip(),
                    str(context.env_vars.get("APP_VERSION") or "").strip(),
                )
                if tag and is_valid_image_tag(tag)
            ),
            "latest",
        )
        container_vm: dict[str, Any] = {
            "name": app_name,
            "image": k8s_policy.image or f"{app_name}:{raw_tag}",
            "ports": [{"containerPort": port}],
            "resources": {
                "requests": {"cpu": cpu_req, "memory": mem_req},
                "limits": {"cpu": cpu_limit, "memory": mem_limit},
            },
            "livenessProbe": liveness_probe,
            "readinessProbe": readiness_probe,
            "envFrom": env_from,
        }

        repo_root: str | None = context.repo_root or None
        templates_dir: str | None = policy.engine.templates_dir
        namespace: str | None = k8s_policy.namespace

        deployment_vm: dict[str, Any] = {
            "app_name": app_name,
            "namespace": namespace,
            "replicas": k8s_policy.replicas,
            "container": container_vm,
        }
        service_vm: dict[str, Any] = {
            "app_name": app_name,
            "service_name": f"{app_name}-service",
            "namespace": namespace,
            "service_type": k8s_policy.service_type,
            "ports": [
                {
                    "protocol": "TCP",
                    "port": 80,
                    "targetPort": port,
                }
            ],
        }
        ingress_vm: dict[str, Any] = {
            "app_name": app_name,
            "ingress_name": f"{app_name}-ingress",
            "namespace": namespace,
            "ingress_class_name": "nginx",
            "rules": [
                {
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": f"{app_name}-service",
                                        "port": {"number": 80},
                                    }
                                },
                            }
                        ]
                    }
                }
            ],
        }
        kind_vm: dict[str, Any] = {
            "cluster_name": f"{app_name}-cluster",
            "nodes": [
                {
                    "role": "control-plane",
                    "kubeadmConfigPatches": [
                        'kind: InitConfiguration\nnodeRegistration:\n  kubeletExtraArgs:\n    node-labels: "ingress-ready=true"\n'
                    ],
                    "extraPortMappings": [
                        {
                            "containerPort": 80,
                            "hostPort": 80,
                            "protocol": "TCP",
                        },
                        {
                            "containerPort": 443,
                            "hostPort": 443,
                            "protocol": "TCP",
                        },
                    ],
                }
            ],
        }

        outputs: dict[str, str] = {
            "k8s/deployment.yaml": render_yaml_template(
                "k8s/deployment.yaml.j2",
                deployment_vm,
                repo_root=repo_root,
                templates_dir=templates_dir,
            ),
            "k8s/service.yaml": render_yaml_template(
                "k8s/service.yaml.j2",
                service_vm,
                repo_root=repo_root,
                templates_dir=templates_dir,
            ),
            "k8s/ingress.yaml": render_yaml_template(
                "k8s/ingress.yaml.j2",
                ingress_vm,
                repo_root=repo_root,
                templates_dir=templates_dir,
            ),
            "k8s/kind-config.yaml": render_yaml_template(
                "k8s/kind-config.yaml.j2",
                kind_vm,
                repo_root=repo_root,
                templates_dir=templates_dir,
            ),
        }

        if safe_env:
            configmap_vm: dict[str, Any] = {
                "app_name": app_name,
                "configmap_name": f"{app_name}-config",
                "namespace": namespace,
                "data": safe_env,
            }
            outputs["k8s/configmap.yaml"] = render_yaml_template(
                "k8s/configmap.yaml.j2",
                configmap_vm,
                repo_root=repo_root,
                templates_dir=templates_dir,
            )

        if declared_secrets:
            secret_vm: dict[str, Any] = {
                "app_name": app_name,
                "secret_name": f"{app_name}-secrets",
                "namespace": namespace,
                "secret_keys": sorted(declared_secrets),
            }
            outputs["k8s/secret.yaml"] = render_yaml_template(
                "k8s/secret.yaml.j2",
                secret_vm,
                repo_root=repo_root,
                templates_dir=templates_dir,
            )

        if k8s_policy.hpa.enabled:
            hpa_vm: dict[str, Any] = {
                "app_name": app_name,
                "hpa_name": f"{app_name}-hpa",
                "namespace": namespace,
                "scale_target_ref": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": app_name,
                },
                "min_replicas": k8s_policy.hpa.min_replicas,
                "max_replicas": k8s_policy.hpa.max_replicas,
                "metrics": [
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "cpu",
                            "target": {
                                "type": "Utilization",
                                "averageUtilization": k8s_policy.hpa.target_cpu_utilization,
                            },
                        },
                    }
                ],
            }
            outputs["k8s/hpa.yaml"] = render_yaml_template(
                "k8s/hpa.yaml.j2",
                hpa_vm,
                repo_root=repo_root,
                templates_dir=templates_dir,
            )

        return outputs
