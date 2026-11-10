"""
Kubernetes Manifest Synthesizer.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List
from ruamel.yaml import YAML
from heurix.core.context import ProjectContext
from heurix.synthesizers.base import BaseSynthesizer


SENSITIVE_KEYWORDS = (
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
)


def _is_sensitive_env_key(key: str) -> bool:
    """Return True if an environment variable key matches any sensitive credential keyword."""
    key_upper = key.upper()
    return any(sk in key_upper for sk in SENSITIVE_KEYWORDS) or "SERVICE_ACCOUNT" in key_upper


class KubernetesSynthesizer(BaseSynthesizer):
    @property
    def name(self) -> str:
        return "Kubernetes Manifests"

    def synthesize(self, context: ProjectContext) -> Dict[str, str]:
        if not context.containers and not any(l.framework for l in context.languages):
            return {}

        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)

        app_name = context.repo_name.lower().replace("_", "-")
        primary = context.get_primary_language()
        is_streamlit = bool(primary and primary.framework == "Streamlit")

        port = 8080
        if is_streamlit:
            port = 8501
        elif context.containers and context.containers[0].exposed_ports:
            port = context.containers[0].exposed_ports[0]
        elif primary and primary.framework == "FastAPI":
            port = 8000
        elif primary and primary.framework in ["Next.js", "Express"]:
            port = 3000

        # Memory baselines
        if primary and primary.language in ["go", "rust"]:
            cpu_req = "50m"
            mem_req = "64Mi"
            mem_limit = "256Mi"
        elif primary and primary.language == "python":
            cpu_req = "100m"
            mem_req = "256Mi"
            mem_limit = "512Mi"
        else:
            cpu_req = "100m"
            mem_req = "256Mi"
            mem_limit = "512Mi"

        if is_streamlit:
            readiness_probe = {
                "httpGet": {"path": "/_stcore/health", "port": port},
                "initialDelaySeconds": 5,
                "periodSeconds": 10,
            }
        else:
            readiness_probe = {
                "tcpSocket": {"port": port},
                "initialDelaySeconds": 5,
                "periodSeconds": 10,
            }

        liveness_probe = {
            "tcpSocket": {"port": port},
            "initialDelaySeconds": 15,
            "periodSeconds": 10,
        }

        container_spec: Dict[str, Any] = {
            "name": app_name,
            "image": f"{app_name}:latest",
            "ports": [{"containerPort": port}],
            "resources": {
                "requests": {"cpu": cpu_req, "memory": mem_req},
                "limits": {"cpu": "500m", "memory": mem_limit},
            },
            "livenessProbe": liveness_probe,
            "readinessProbe": readiness_probe,
        }

        declared_secrets = (
            set(context.required_secrets)
            | set(context.test_secrets)
            | set(context.deployment_secrets)
        )
        safe_env = {
            k: v
            for k, v in context.env_vars.items()
            if k not in declared_secrets and not _is_sensitive_env_key(k)
        }

        env_from: List[Dict[str, Any]] = []
        if safe_env:
            env_from.append({"configMapRef": {"name": f"{app_name}-config"}})
        if declared_secrets:
            env_from.append({
                "secretRef": {
                    "name": f"{app_name}-secrets",
                    "optional": True,
                }
            })

        if env_from:
            container_spec["envFrom"] = env_from

        # 1. Deployment
        deployment: Dict[str, Any] = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": app_name,
                "labels": {"app": app_name},
            },
            "spec": {
                "replicas": 2,
                "selector": {"matchLabels": {"app": app_name}},
                "template": {
                    "metadata": {"labels": {"app": app_name}},
                    "spec": {
                        "containers": [container_spec]
                    },
                },
            },
        }

        # 2. Service
        service: Dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": f"{app_name}-service",
                "labels": {"app": app_name},
            },
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": app_name},
                "ports": [
                    {
                        "protocol": "TCP",
                        "port": 80,
                        "targetPort": port,
                    }
                ],
            },
        }

        # 3. Ingress (Modernized spec with ingressClassName)
        ingress: Dict[str, Any] = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": f"{app_name}-ingress",
            },
            "spec": {
                "ingressClassName": "nginx",
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
            },
        }

        def to_yaml_str(data: dict) -> str:
            s = io.StringIO()
            s.write("# Synthesized deterministically by Heurix (hx)\n")
            yaml.dump(data, s)
            return s.getvalue()

        # 4. Kind Local Development Cluster Config
        kind_config: Dict[str, Any] = {
            "kind": "Cluster",
            "apiVersion": "kind.x-k8s.io/v1alpha4",
            "metadata": {
                "name": f"{app_name}-cluster",
            },
            "nodes": [
                {
                    "role": "control-plane",
                    "kubeadmConfigPatches": [
                        "kind: InitConfiguration\nnodeRegistration:\n  kubeletExtraArgs:\n    node-labels: \"ingress-ready=true\"\n"
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

        outputs: Dict[str, str] = {
            "k8s/deployment.yaml": to_yaml_str(deployment),
            "k8s/service.yaml": to_yaml_str(service),
            "k8s/ingress.yaml": to_yaml_str(ingress),
            "k8s/kind-config.yaml": to_yaml_str(kind_config),
        }

        if safe_env:
            configmap: Dict[str, Any] = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": f"{app_name}-config",
                    "labels": {"app": app_name},
                },
                "data": safe_env,
            }
            outputs["k8s/configmap.yaml"] = to_yaml_str(configmap)

        return outputs
