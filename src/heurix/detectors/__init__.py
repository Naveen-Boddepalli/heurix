"""
Modular detectors for Heurix.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        import tomllib  # type: ignore

from heurix.core.context import MonorepoPackage, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.core.monorepo import discover_monorepo_topology
from heurix.core.policy import (
    _LANG_KEY_ALIASES,
    apply_language_version_policy as _apply_language_version_policy,
    apply_policy_to_context,
    normalize_string_list as _normalize_string_list,
    parse_heurix_policy,
)
from heurix.detectors.base import BaseDetector
from heurix.detectors.cloud_detector import CloudDetector
from heurix.detectors.cpp_detector import CppDetector
from heurix.detectors.docker_detector import DockerDetector
from heurix.detectors.env_detector import EnvDetector
from heurix.detectors.go_detector import GoDetector
from heurix.detectors.node_detector import NodeDetector
from heurix.detectors.python_detector import PythonDetector
from heurix.detectors.rust_detector import RustDetector

ALL_DETECTORS: List[BaseDetector] = [
    PythonDetector(),
    NodeDetector(),
    RustDetector(),
    GoDetector(),
    CppDetector(),
    DockerDetector(),
    EnvDetector(),
    CloudDetector(),
]


def analyze_repository(root_dir: str | Path) -> ProjectContext:
    """
    Scans and analyzes repository, producing the ProjectContext IR.
    """
    root_path = Path(root_dir).resolve()
    indexer = RepoIndexer(root_path)

    repo_name = root_path.name
    context = ProjectContext(
        repo_name=repo_name,
        repo_root=str(root_path),
        language_scores=indexer.compute_language_scores(),
    )
    context.add_explain(f"🔍 Scanning repository at {root_path} (indexed {len(indexer.files)} files)...")

    for detector in ALL_DETECTORS:
        if detector.detect(indexer):
            detector.analyze(indexer, context)

    # Reconcile monorepo topology deterministically across all detectors
    topology = discover_monorepo_topology(indexer)
    deduped_pkgs: Dict[Tuple[str, str], MonorepoPackage] = {}
    for pkg in context.monorepo_packages:
        pkg_key = (pkg.path, pkg.language.lower())
        if pkg_key not in deduped_pkgs:
            deduped_pkgs[pkg_key] = pkg
    context.monorepo_packages = [deduped_pkgs[k] for k in sorted(deduped_pkgs)]

    if (
        topology.is_monorepo
        or len(context.monorepo_packages) >= 2
        or (
            len(context.monorepo_packages) == 1
            and any(l.working_dir == "." and l.is_workspace_root is False for l in context.languages)
        )
    ):
        context.is_monorepo = True

    # Load .heurix.toml policy configuration if present
    config_path = root_path / ".heurix.toml"
    if config_path.exists():
        try:
            raw_cfg = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(raw_cfg)
            if not isinstance(config, dict):
                raise ValueError(".heurix.toml root must be a table")
            context.policy_config = config
            context.add_explain("Loaded configuration policy from .heurix.toml")

            policy, policy_warnings = parse_heurix_policy(config)
            for warning in policy_warnings:
                context.add_explain(warning)
            apply_policy_to_context(context, policy, raw_config=config)
        except Exception as e:
            context.add_explain(f"Warning: Failed to parse .heurix.toml: {e}")

    return context
