"""
Maintenance and Hygiene Workflow Synthesizer (Dependabot).
"""

from __future__ import annotations

import io
from typing import Any, Dict, List
from ruamel.yaml import YAML
from heurix.core.context import ProjectContext
from heurix.synthesizers.base import BaseSynthesizer


class MaintenanceSynthesizer(BaseSynthesizer):
    @property
    def name(self) -> str:
        return "Dependabot & Maintenance"

    def synthesize(self, context: ProjectContext) -> Dict[str, str]:
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)

        updates: List[Dict[str, Any]] = [
            {
                "package-ecosystem": "github-actions",
                "directory": "/",
                "schedule": {"interval": "weekly"},
                "open-pull-requests-limit": 10,
            }
        ]

        for lang in context.languages:
            if lang.language == "python":
                updates.append({
                    "package-ecosystem": "pip",
                    "directory": "/",
                    "schedule": {"interval": "weekly"},
                    "open-pull-requests-limit": 10,
                })
            elif lang.language == "node":
                updates.append({
                    "package-ecosystem": "npm",
                    "directory": "/",
                    "schedule": {"interval": "weekly"},
                    "open-pull-requests-limit": 10,
                })
                # If monorepo packages exist
                for pkg in context.monorepo_packages:
                    if pkg.language == "node":
                        updates.append({
                            "package-ecosystem": "npm",
                            "directory": f"/{pkg.path}",
                            "schedule": {"interval": "weekly"},
                            "open-pull-requests-limit": 5,
                        })
            elif lang.language == "rust":
                updates.append({
                    "package-ecosystem": "cargo",
                    "directory": "/",
                    "schedule": {"interval": "weekly"},
                    "open-pull-requests-limit": 10,
                })
            elif lang.language == "go":
                updates.append({
                    "package-ecosystem": "gomod",
                    "directory": "/",
                    "schedule": {"interval": "weekly"},
                    "open-pull-requests-limit": 10,
                })

        if context.containers:
            updates.append({
                "package-ecosystem": "docker",
                "directory": "/",
                "schedule": {"interval": "weekly"},
                "open-pull-requests-limit": 10,
            })

        dependabot_config = {
            "version": 2,
            "updates": updates,
        }

        stream = io.StringIO()
        stream.write("# Synthesized deterministically by Heurix (hx)\n")
        yaml.dump(dependabot_config, stream)

        return {".github/dependabot.yml": stream.getvalue()}
