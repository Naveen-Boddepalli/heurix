"""
Docker and Docker Compose Detector.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List
from ruamel.yaml import YAML
from heurix.core.context import ContainerContext, ProjectContext, ServiceRequirement
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


class DockerDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "Docker"

    def detect(self, indexer: RepoIndexer) -> bool:
        indicators = [
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ]
        return any(indexer.has_file(f) for f in indicators) or bool(indexer.find_files("*Dockerfile*"))

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing Docker configurations...")

        yaml = YAML(typ="safe")

        # 1. Inspect Dockerfile
        dockerfiles = indexer.find_by_name("Dockerfile") + [f for f in indexer.find_files("Dockerfile*") if "/" not in f]
        for df_name in set(dockerfiles):
            content = indexer.read_text(df_name)
            if not content:
                continue

            exposed_ports: List[int] = []
            base_image = ""
            has_healthcheck = bool(re.search(r"^\s*HEALTHCHECK", content, re.MULTILINE))

            for line in content.splitlines():
                line = line.strip()
                if line.startswith("FROM ") and not base_image:
                    base_image = line.split()[1]
                elif line.startswith("EXPOSE "):
                    parts = line.replace("EXPOSE", "").strip().split()
                    for p in parts:
                        clean_p = p.split("/")[0]
                        if clean_p.isdigit():
                            exposed_ports.append(int(clean_p))

            context.containers.append(
                ContainerContext(
                    dockerfile_path=df_name,
                    exposed_ports=exposed_ports,
                    base_image=base_image,
                    has_healthcheck=has_healthcheck,
                )
            )
            context.add_explain(
                f"Parsed Dockerfile '{df_name}': base={base_image}, exposed={exposed_ports}, healthcheck={has_healthcheck}"
            )

        # 2. Inspect docker-compose.yml / compose.yml
        compose_files = [
            f for f in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
            if indexer.has_file(f)
        ]

        for cf in compose_files:
            content = indexer.read_text(cf)
            if not content:
                continue
            try:
                data = yaml.load(content)
                if not isinstance(data, dict):
                    continue

                services = data.get("services", {})
                for svc_name, svc_cfg in services.items():
                    if not isinstance(svc_cfg, dict):
                        continue

                    image = str(svc_cfg.get("image", ""))
                    ports_raw = svc_cfg.get("ports", [])
                    env_raw = svc_cfg.get("environment", {})

                    parsed_ports: List[int] = []
                    for pr in ports_raw:
                        port_str = str(pr).split(":")[0].strip("'\"")
                        if port_str.isdigit():
                            parsed_ports.append(int(port_str))

                    parsed_env: Dict[str, str] = {}
                    if isinstance(env_raw, dict):
                        for k, v in env_raw.items():
                            parsed_env[str(k)] = str(v)
                    elif isinstance(env_raw, list):
                        for item in env_raw:
                            if "=" in str(item):
                                k, v = str(item).split("=", 1)
                                parsed_env[k.strip()] = v.strip()

                    # Deduplicate or add service
                    existing = [s for s in context.services if s.name.lower() == svc_name.lower()]
                    if not existing:
                        context.services.append(
                            ServiceRequirement(
                                name=svc_name,
                                image=image or f"{svc_name}:latest",
                                ports=parsed_ports,
                                env=parsed_env,
                                source_file=cf,
                            )
                        )
                        context.add_explain(
                            f"Detected Service from {cf}: '{svc_name}' (image: {image or svc_name}, ports: {parsed_ports})"
                        )
            except Exception as e:
                context.add_explain(f"Warning: Failed to parse {cf}: {e}")
