"""
Drift Detection Engine for Heurix (`hx check`).
Compares codebase fingerprint against existing YAML infrastructure configurations.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, NamedTuple
from ruamel.yaml import YAML
from heurix.core.context import ProjectContext


class DriftFinding(NamedTuple):
    file_path: str
    issue: str
    severity: str  # "WARNING", "ERROR", "INFO"
    recommendation: str


class DriftDetector:
    """
    Detects configuration drift between the codebase IR and existing YAML files.
    """

    def __init__(self, repo_root: str | Path):
        self.root = Path(repo_root).resolve()
        self.yaml = YAML(typ="safe")

    def check_drift(self, context: ProjectContext, synthesized_files: dict[str, str]) -> List[DriftFinding]:
        findings: List[DriftFinding] = []

        for rel_path, expected_content in synthesized_files.items():
            file_path = self.root / rel_path

            if not file_path.exists():
                findings.append(
                    DriftFinding(
                        file_path=rel_path,
                        issue="File does not exist in repository.",
                        severity="WARNING",
                        recommendation=f"Run 'hx generate' to synthesize {rel_path}.",
                    )
                )
                continue

            try:
                existing_text = file_path.read_text(encoding="utf-8", errors="replace")
                existing_doc = self.yaml.load(existing_text)
            except Exception as e:
                findings.append(
                    DriftFinding(
                        file_path=rel_path,
                        issue=f"Existing YAML file is malformed: {e}",
                        severity="ERROR",
                        recommendation="Fix YAML syntax or run 'hx generate --force'.",
                    )
                )
                continue

            # Check workflow-specific drift
            if ".github/workflows" in rel_path and isinstance(existing_doc, dict):
                test_job = existing_doc.get("jobs", {}).get("test", {})
                existing_services = test_job.get("services", {})

                # Check if detected backing services are missing in workflow
                for svc in context.services:
                    svc_name = svc.name.lower()
                    if svc_name not in [s.lower() for s in existing_services.keys()]:
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=f"Service '{svc.name}' is required by codebase dependencies ({svc.source_file}) but missing from workflow.",
                                severity="WARNING",
                                recommendation=f"Run 'hx generate' to inject service '{svc.name}'.",
                            )
                        )

                # Check runtime version drift
                existing_str = str(existing_doc)
                for lang in context.languages:
                    if lang.runtime_version not in existing_str and lang.runtime_version != "latest":
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue=f"Runtime version mismatch: codebase specifies {lang.language} {lang.runtime_version} ({lang.version_source}), not found in workflow.",
                                severity="WARNING",
                                recommendation=f"Run 'hx generate' to update {lang.language} version.",
                            )
                        )

                # Check package manager drift
                for lang in context.languages:
                    if lang.package_manager == "uv" and "setup-uv" not in existing_str:
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue="uv package manager detected in codebase (uv.lock), but workflow does not use astral-sh/setup-uv.",
                                severity="WARNING",
                                recommendation="Run 'hx generate' to optimize workflow for uv.",
                            )
                        )
                    elif lang.package_manager == "pnpm" and "pnpm" not in existing_str:
                        findings.append(
                            DriftFinding(
                                file_path=rel_path,
                                issue="pnpm package manager detected in codebase, but workflow does not use pnpm.",
                                severity="WARNING",
                                recommendation="Run 'hx generate' to update workflow to pnpm.",
                            )
                        )

        return findings
