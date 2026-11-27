"""
The composite GitHub Action in action.yml: inputs are wired through env, never expanded into scripts.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION = YAML(typ="safe").load((REPO_ROOT / "action.yml").read_text(encoding="utf-8"))
STEPS = ACTION["runs"]["steps"]
CHECK_STEP = next(s for s in STEPS if s.get("id") == "check")


def test_action_is_composite_with_documented_inputs():
    assert ACTION["runs"]["using"] == "composite"
    assert set(ACTION["inputs"]) == {"path", "security", "format", "output-file", "fail-on-findings", "version"}
    assert ACTION["outputs"]["exit-code"]["value"] == "${{ steps.check.outputs.exit-code }}"
    docs = (REPO_ROOT / "docs" / "drift-detection.md").read_text(encoding="utf-8")
    for name in ACTION["inputs"]:
        assert f"| `{name}` |" in docs


def test_action_scripts_never_expand_expressions():
    # Inputs reach the scripts only through env:, so a crafted input can't inject shell code.
    used_inputs: set[str] = set()
    for step in STEPS:
        assert step["shell"] == "bash"
        assert "${{" not in step["run"]
        for value in step.get("env", {}).values():
            used_inputs.update(re.findall(r"\binputs\.([\w-]+)", value))
    assert used_inputs == set(ACTION["inputs"])


@pytest.mark.skipif(sys.platform == "win32", reason="the action supports Linux and macOS runners")
@pytest.mark.parametrize(
    ("repo_has_drift", "fail_on_findings", "fmt", "step_code", "hx_code"),
    [
        (False, "true", "text", 0, "0"),
        (True, "true", "text", 1, "1"),
        (True, "false", "json", 0, "1"),
        (False, "false", "xml", 2, "2"),
    ],
)
def test_check_step_exit_codes(tmp_path, repo_has_drift, fail_on_findings, fmt, step_code, hx_code):
    """Run the action's check step with the real hx, as the runner would."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("requests\n", encoding="utf-8")
    hx = [sys.executable, "-m", "heurix.cli"]
    subprocess.run([*hx, "generate", "--path", str(repo), "--yes", "--no-explain", "--no-k8s"], check=True)
    if repo_has_drift:
        (repo / "requirements.txt").write_text("requests\npsycopg2\n", encoding="utf-8")
    output = tmp_path / "github_output"
    output.touch()
    env = {
        **os.environ,
        "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
        "GITHUB_OUTPUT": str(output),
        "HX_PATH": str(repo),
        "HX_SECURITY": "true",
        "HX_FORMAT": fmt,
        "HX_OUTPUT_FILE": str(tmp_path / "report"),
        "HX_FAIL": fail_on_findings,
    }
    result = subprocess.run(["bash", "-c", CHECK_STEP["run"]], env=env, capture_output=True, text=True)
    assert result.returncode == step_code, result.stderr
    assert output.read_text(encoding="utf-8").strip() == f"exit-code={hx_code}"
