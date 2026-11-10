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


def _parse_port_token(token: str) -> List[int]:
    """Parse a single port or 'start-end' range token within valid bounds (1-65535)."""
    cleaned = token.strip()
    if not cleaned:
        return []

    if "-" in cleaned:
        start_str, end_str = cleaned.split("-", 1)
        start_str, end_str = start_str.strip(), end_str.strip()
        if start_str.isdigit() and end_str.isdigit():
            start, end = int(start_str), int(end_str)
            if 1 <= start <= end <= 65535:
                return list(range(start, end + 1))
        return []

    if cleaned.isdigit():
        port = int(cleaned)
        if 1 <= port <= 65535:
            return [port]

    return []


def extract_container_ports(port_entry: Any) -> List[int]:
    """
    Extract internal container port(s) from Docker Compose port definitions:
    - 80 -> [80]
    - "8080:80" -> [80]
    - "127.0.0.1:8080:80/tcp" -> [80]
    - "3000-3002:4000-4002" -> [4000, 4001, 4002]
    - {"target": 80, "published": 8080} -> [80]
    """
    if isinstance(port_entry, bool) or port_entry is None:
        return []

    if isinstance(port_entry, int):
        return [port_entry] if 1 <= port_entry <= 65535 else []

    if isinstance(port_entry, dict):
        target = port_entry.get("target")
        if target is None or isinstance(target, bool):
            return []
        if isinstance(target, int):
            return [target] if 1 <= target <= 65535 else []
        return _parse_port_token(str(target).strip("'\""))

    s = str(port_entry).strip().strip("'\"")
    if not s:
        return []

    # Strip protocol suffix (/tcp, /udp, /sctp)
    if "/" in s:
        s = s.split("/", 1)[0]

    # Split colon tokens: host:container, ip:host:container, or container
    container_token = s.split(":")[-1].strip()
    return _parse_port_token(container_token)


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
            build_target = None
            has_healthcheck = bool(re.search(r"^\s*HEALTHCHECK", content, re.MULTILINE))

            # Inside Dockerfile loop: capture final stage image and build target
            for line in content.splitlines():
                line_clean = line.strip()
                if line_clean.upper().startswith("FROM "):
                    parts = line_clean.split()
                    if len(parts) >= 2:
                        base_image = parts[1]
                        upper_parts = [p.upper() for p in parts]
                        if "AS" in upper_parts:
                            as_idx = upper_parts.index("AS")
                            if as_idx + 1 < len(parts):
                                build_target = parts[as_idx + 1]
                        else:
                            build_target = None
                elif line_clean.upper().startswith("EXPOSE "):
                    parts = line_clean.replace("EXPOSE", "").strip().split()
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
                    build_target=build_target,
                )
            )
            context.add_explain(
                f"Parsed Dockerfile '{df_name}': base={base_image}, exposed={exposed_ports}, healthcheck={has_healthcheck}, build_target={build_target}"
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

                    # Inside compose services loop: skip local build containers or services without an image
                    if "build" in svc_cfg and not svc_cfg.get("image"):
                        context.add_explain(f"Skipping local build container '{svc_name}' from CI backing services")
                        continue
                    if not svc_cfg.get("image"):
                        context.add_explain(f"Skipping service '{svc_name}' without image from CI backing services")
                        continue

                    image = str(svc_cfg.get("image", ""))
                    ports_raw = svc_cfg.get("ports") or []
                    env_raw = svc_cfg.get("environment") or {}

                    parsed_ports: List[int] = []
                    if isinstance(ports_raw, list):
                        for pr in ports_raw:
                            for port in extract_container_ports(pr):
                                if port not in parsed_ports:
                                    parsed_ports.append(port)

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
