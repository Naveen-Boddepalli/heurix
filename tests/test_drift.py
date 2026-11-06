"""
Tests for Drift Detection.
"""

from __future__ import annotations

from pathlib import Path
from heurix.core.context import LanguageContext, ProjectContext, ServiceRequirement
from heurix.core.drift import DriftDetector


def test_drift_detector_flags_missing_service(tmp_path: Path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
        encoding="utf-8",
    )

    context = ProjectContext(
        repo_name="demo",
        repo_root=str(tmp_path),
        languages=[
            LanguageContext(
                language="python",
                runtime_version="3.12",
                version_source=".python-version",
                package_manager="pip",
                install_cmd="pip install -r requirements.txt",
            )
        ],
        services=[
            ServiceRequirement(
                name="redis",
                image="redis:7-alpine",
                ports=[6379],
                source_file="pyproject.toml",
            )
        ],
    )

    synthesized = {".github/workflows/ci.yml": "dummy"}
    detector = DriftDetector(tmp_path)
    findings = detector.check_drift(context, synthesized)

    assert len(findings) > 0
    assert any("redis" in f.issue.lower() for f in findings)
