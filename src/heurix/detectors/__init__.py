"""
Modular detectors for Heurix.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List
from heurix.core.context import ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector
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
]


def analyze_repository(root_dir: str | Path) -> ProjectContext:
    """
    Scans and analyzes repository, producing the ProjectContext IR.
    """
    root_path = Path(root_dir).resolve()
    indexer = RepoIndexer(root_path)

    repo_name = root_path.name
    context = ProjectContext(repo_name=repo_name, repo_root=str(root_path))
    context.add_explain(f"🔍 Scanning repository at {root_path} (indexed {len(indexer.files)} files)...")

    for detector in ALL_DETECTORS:
        if detector.detect(indexer):
            detector.analyze(indexer, context)

    return context
