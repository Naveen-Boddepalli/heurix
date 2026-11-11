"""
Maintenance and Hygiene Workflow Synthesizer (Dependabot).
"""

from __future__ import annotations

import posixpath
from typing import Any, Dict, List, Set, Tuple
from heurix.core.context import ProjectContext
from heurix.core.policy import HeurixPolicy
from heurix.synthesizers.base import BaseSynthesizer
from heurix.synthesizers.templating import render_yaml_template

ECOSYSTEM_MAP: Dict[str, str] = {
    "python": "pip",
    "node": "npm",
    "rust": "cargo",
    "go": "gomod",
}


def _normalize_dir(path: str) -> str:
    """Normalize a relative package or directory path to '/' or '/<subpath>'."""
    cleaned = (path or "").strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.strip("/")
    if not cleaned or cleaned == ".":
        return "/"
    return f"/{cleaned}"


class MaintenanceSynthesizer(BaseSynthesizer):
    @property
    def name(self) -> str:
        return "Dependabot & Maintenance"

    def synthesize(self, context: ProjectContext) -> Dict[str, str]:
        policy = HeurixPolicy.from_raw(context.policy_config)

        seen_pairs: Set[Tuple[str, str]] = {("github-actions", "/")}
        updates: List[Dict[str, Any]] = [
            {
                "package-ecosystem": "github-actions",
                "directory": "/",
                "schedule": {"interval": "weekly"},
                "open-pull-requests-limit": 10,
            }
        ]

        pkg_entries: List[Tuple[str, str, int]] = []
        subpkg_langs: Set[str] = set()

        sorted_packages = sorted(
            context.monorepo_packages,
            key=lambda p: (_normalize_dir(p.path), p.language.lower()),
        )
        for pkg in sorted_packages:
            lang_key = pkg.language.lower()
            eco = ECOSYSTEM_MAP.get(lang_key)
            if not eco:
                continue
            directory = _normalize_dir(pkg.path)
            if directory != "/":
                subpkg_langs.add(lang_key)
            pair = (eco, directory)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            limit = 10 if directory == "/" else 5
            pkg_entries.append((eco, directory, limit))

        for lang in context.languages:
            lang_key = lang.language.lower()
            eco = ECOSYSTEM_MAP.get(lang_key)
            if not eco:
                continue
            directory = _normalize_dir(lang.working_dir)
            if lang.is_workspace_root is True and context.monorepo_packages:
                continue
            if lang.is_workspace_root is None and directory == "/" and lang_key in subpkg_langs:
                continue
            pair = (eco, directory)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            limit = 10 if directory == "/" else 5
            pkg_entries.append((eco, directory, limit))

        pkg_entries.sort(key=lambda item: (0 if item[1] == "/" else 1, item[1], item[0]))

        docker_entries: List[Tuple[str, str, int]] = []
        for container in context.containers:
            raw_df = (container.dockerfile_path or "").strip().replace("\\", "/")
            while raw_df.startswith("./"):
                raw_df = raw_df[2:]
            parent_dir = posixpath.dirname(raw_df)
            directory = _normalize_dir(parent_dir)
            pair = ("docker", directory)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            docker_entries.append(("docker", directory, 10))

        docker_entries.sort(key=lambda item: (0 if item[1] == "/" else 1, item[1]))

        for eco, directory, limit in (*pkg_entries, *docker_entries):
            updates.append({
                "package-ecosystem": eco,
                "directory": directory,
                "schedule": {"interval": "weekly"},
                "open-pull-requests-limit": limit,
            })

        rendered = render_yaml_template(
            "dependabot/dependabot.yml.j2",
            {"updates": updates},
            repo_root=context.repo_root or None,
            templates_dir=policy.engine.templates_dir,
        )
        return {".github/dependabot.yml": rendered}
