"""
Modular detectors for Heurix.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        import tomllib  # type: ignore

from heurix.core.context import ProjectContext
from heurix.core.indexer import RepoIndexer
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

    # 3. Load .heurix.toml policy configuration if present
    config_path = root_path / ".heurix.toml"
    if config_path.exists():
        try:
            raw_cfg = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(raw_cfg)
            context.policy_config = config
            context.add_explain("Loaded configuration policy from .heurix.toml")

            # Apply engine runner override
            engine_cfg = config.get("engine", {})
            if "runner" in engine_cfg:
                context.runner = str(engine_cfg["runner"])
                context.add_explain(f"Set CI runner to '{context.runner}' (via .heurix.toml)")

            # Apply runtime version overrides
            overrides = config.get("overrides", {})
            for lang_name, version in overrides.items():
                version_str = str(version)
                lang_ctx = context.get_language(lang_name)
                if lang_ctx:
                    old_ver = lang_ctx.runtime_version
                    lang_ctx.runtime_version = version_str
                    lang_ctx.version_source = ".heurix.toml"
                    context.add_explain(
                        f"Overrode {lang_name} version: {old_ver} -> {version_str} (via .heurix.toml)"
                    )
        except Exception as e:
            context.add_explain(f"Warning: Failed to parse .heurix.toml: {e}")

    return context
