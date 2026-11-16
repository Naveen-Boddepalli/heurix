"""
`[ci].paths` / `[ci].paths_ignore` policy: trigger path filters in the generated CI workflow.
"""

from __future__ import annotations

import json
from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from heurix.cli import app
from heurix.core.merger import SmartMerger
from heurix.core.policy import parse_heurix_policy

runner = CliRunner()


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _generate(repo: Path) -> dict:
    res = runner.invoke(app, ["generate", "--path", str(repo), "--yes", "--non-interactive", "--no-k8s"])
    assert res.exit_code == 0, res.stdout
    return YAML(typ="safe").load((repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _python_repo(root: Path) -> None:
    _write(root, "requirements.txt", "pytest\n")
    _write(root, "app.py", "x = 1\n")
    _write(root, "tests/test_app.py", "def test_x():\n    assert True\n")


def _pnpm_monorepo(root: Path) -> None:
    _write(root, "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
    _write(root, "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
    _write(root, "package.json", '{"name": "mono", "private": true}')
    for name in ("api", "web"):
        _write(root, f"apps/{name}/package.json", json.dumps({"name": name, "scripts": {"test": "vitest run"}}))
        _write(root, f"apps/{name}/index.ts", "export {}\n")


# --- policy parsing -------------------------------------------------------


def test_policy_defaults_have_no_path_filters():
    policy, warnings = parse_heurix_policy({})
    assert policy.ci.paths is None
    assert policy.ci.paths_ignore == []
    assert not policy.ci.has_path_filters
    assert warnings == []


def test_policy_accepts_both_spellings_scalars_and_dedupes():
    policy, _ = parse_heurix_policy({"ci": {"paths-ignore": ["docs/**", "docs/**", "*.md"]}})
    assert policy.ci.paths_ignore == ["docs/**", "*.md"]

    policy, _ = parse_heurix_policy({"ci": {"paths_ignore": "docs/**", "paths": "src/**"}})
    assert policy.ci.paths_ignore == ["docs/**"]
    assert policy.ci.paths == ["src/**"]
    assert policy.ci.has_path_filters


def test_policy_prunes_only_invalid_patterns():
    policy, warnings = parse_heurix_policy({"ci": {"paths": ["src/**", "!docs/**", "  "], "pin_actions": False}})
    assert policy.ci.paths == ["src/**"]
    assert policy.ci.pin_actions is False
    assert any("ci.paths" in w for w in warnings)


# --- synthesis -------------------------------------------------------------


def test_single_repo_paths_ignore_emitted_on_both_triggers(tmp_path: Path):
    _python_repo(tmp_path)
    _write(tmp_path, ".heurix.toml", '[ci]\npaths_ignore = ["docs/**", "**/*.md"]\n')
    doc = _generate(tmp_path)
    for trigger in ("push", "pull_request"):
        assert doc["on"][trigger]["paths-ignore"] == ["docs/**", "**/*.md"]
        assert "paths" not in doc["on"][trigger]


def test_single_repo_explicit_paths(tmp_path: Path):
    _python_repo(tmp_path)
    _write(tmp_path, ".heurix.toml", '[ci]\npaths = ["app.py", "tests/**"]\n')
    doc = _generate(tmp_path)
    assert doc["on"]["push"]["paths"] == ["app.py", "tests/**"]
    assert "paths-ignore" not in doc["on"]["push"]


def test_monorepo_paths_ignore_folds_into_negated_paths(tmp_path: Path):
    _pnpm_monorepo(tmp_path)
    _write(tmp_path, ".heurix.toml", '[ci]\npaths_ignore = ["**/*.md"]\n')
    doc = _generate(tmp_path)
    paths = doc["on"]["pull_request"]["paths"]
    # GitHub forbids `paths` and `paths-ignore` together, so ignores become trailing negations.
    assert paths[:2] == ["*", ".github/workflows/**"]
    assert "apps/api/**" in paths and "apps/web/**" in paths
    assert paths[-1] == "!**/*.md"
    assert "paths-ignore" not in doc["on"]["pull_request"]


def test_monorepo_explicit_paths_replace_inferred(tmp_path: Path):
    _pnpm_monorepo(tmp_path)
    _write(tmp_path, ".heurix.toml", '[ci]\npaths = ["apps/web/**"]\n')
    doc = _generate(tmp_path)
    assert doc["on"]["push"]["paths"] == ["apps/web/**"]


def test_monorepo_empty_paths_disables_filtering(tmp_path: Path):
    _pnpm_monorepo(tmp_path)
    _write(tmp_path, ".heurix.toml", "[ci]\npaths = []\n")
    doc = _generate(tmp_path)
    assert "paths" not in doc["on"]["push"]
    assert "paths-ignore" not in doc["on"]["push"]


# --- regeneration / merge ---------------------------------------------------


def test_regenerate_applies_changed_policy_paths(tmp_path: Path):
    _pnpm_monorepo(tmp_path)
    _generate(tmp_path)
    _write(tmp_path, ".heurix.toml", '[ci]\npaths = ["apps/api/**"]\n')
    doc = _generate(tmp_path)
    assert doc["on"]["push"]["paths"] == ["apps/api/**"]

    # Switching to ignore-only on a single-package repo must drop the stale `paths`.
    _python_repo(tmp_path / "solo")
    _write(tmp_path / "solo", ".heurix.toml", '[ci]\npaths = ["app.py"]\n')
    _generate(tmp_path / "solo")
    _write(tmp_path / "solo", ".heurix.toml", '[ci]\npaths_ignore = ["docs/**"]\n')
    doc = _generate(tmp_path / "solo")
    assert "paths" not in doc["on"]["push"]
    assert doc["on"]["push"]["paths-ignore"] == ["docs/**"]


def test_merger_without_policy_keeps_user_paths():
    existing = "name: CI\non:\n  push:\n    branches: [main]\n    paths: [custom/**]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
    new = "name: CI\non:\n  push:\n    branches: [main]\n    paths-ignore: [docs/**]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
    kept = YAML(typ="safe").load(SmartMerger().merge_yaml(existing, new))
    assert kept["on"]["push"]["paths"] == ["custom/**"]

    merger = SmartMerger(authoritative_trigger_paths=True)
    synced = YAML(typ="safe").load(merger.merge_yaml(existing, new))
    assert "paths" not in synced["on"]["push"]
    assert synced["on"]["push"]["paths-ignore"] == ["docs/**"]
    assert any("on.push.paths" in note for note in merger.replaced)
