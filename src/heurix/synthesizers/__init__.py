"""
Synthesizers module for Heurix.
"""

from __future__ import annotations

from typing import Dict, List
from heurix.core.context import ProjectContext
from heurix.synthesizers.base import BaseSynthesizer
from heurix.synthesizers.github_actions import GitHubActionsSynthesizer
from heurix.synthesizers.kubernetes import KubernetesSynthesizer
from heurix.synthesizers.maintenance import MaintenanceSynthesizer

DEFAULT_SYNTHESIZERS: List[BaseSynthesizer] = [
    GitHubActionsSynthesizer(),
    MaintenanceSynthesizer(),
    KubernetesSynthesizer(),
]


def synthesize_all(
    context: ProjectContext,
    include_k8s: bool = True,
    include_dependabot: bool = True,
) -> Dict[str, str]:
    """
    Runs all synthesizers against the project context.
    Returns mapping of { relative_path: yaml_content }.
    """
    results: Dict[str, str] = {}
    for syn in DEFAULT_SYNTHESIZERS:
        if isinstance(syn, KubernetesSynthesizer) and not include_k8s:
            continue
        if isinstance(syn, MaintenanceSynthesizer) and not include_dependabot:
            continue
        files = syn.synthesize(context)
        results.update(files)
    return results
