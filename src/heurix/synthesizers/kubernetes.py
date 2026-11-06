"""
Kubernetes Manifest Synthesizer.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List
from ruamel.yaml import YAML
from heurix.core.context import ProjectContext
from heurix.synthesizers.base import BaseSynthesizer


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
        port = 8080
        if context.containers and context.containers[0].exposed_ports:
            port = context.containers[0].exposed_ports[0]
        elif context.get_primary_language() and context.get_primary_language().framework == "FastAPI":
            port = 8000
        elif context.get_primary_language() and context.get_primary_language().framework in ["Next.js", "Express"]:
            port = 3000

        # Memory baselines
        primary = context.get_primary_language()
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
                        "containers": [
                            {
                                "name": app_name,
                                "image": f"{app_name}:latest",
                                "ports": [{"containerPort": port}],
                                "resources": {
                                    "requests": {"cpu": cpu_req, "memory": mem_req},
                                    "limits": {"cpu": "500m", "memory": mem_limit},
                                },
                                "livenessProbe": {
                                    "tcpSocket": {"port": port},
                                    "initialDelaySeconds": 15,
                                    "periodSeconds": 10,
                                },
                                "readinessProbe": {
                                    "tcpSocket": {"port": port},
                                    "initialDelaySeconds": 5,
                                    "periodSeconds": 10,
                                },
                            }
                        ]
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

        # 3. Ingress
        ingress: Dict[str, Any] = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": f"{app_name}-ingress",
                "annotations": {
                    "kubernetes.io/ingress.class": "nginx",
                },
            },
            "spec": {
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
                ]
            },
        }

        def to_yaml_str(data: dict) -> str:
            s = io.StringIO()
            s.write("# Synthesized deterministically by Heurix (hx)\n")
            yaml.dump(data, s)
            return s.getvalue()

        return {
            "k8s/deployment.yaml": to_yaml_str(deployment),
            "k8s/service.yaml": to_yaml_str(service),
            "k8s/ingress.yaml": to_yaml_str(ingress),
        }
