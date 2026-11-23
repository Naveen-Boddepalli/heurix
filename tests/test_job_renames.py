"""
Regression tests: regenerating a workflow after the repository's languages change.

One root language gives a `test` job; several give `test-<language>`. The job Heurix generated
under the old ID must not be kept as a custom job next to its replacement (running tests twice),
while jobs the user wrote and anything marked `# @heurix:preserve` stay.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from heurix.cli import app
from heurix.core.merger import SmartMerger

runner = CliRunner()

CI = Path(".github") / "workflows" / "ci.yml"


def _generate(repo: Path) -> tuple[dict, str]:
    res = runner.invoke(app, ["generate", "--path", str(repo), "--yes", "--no-explain", "--no-k8s"])
    assert res.exit_code == 0, res.stdout
    doc = YAML(typ="safe").load((repo / CI).read_text(encoding="utf-8"))
    return doc, res.stdout


def _python(repo: Path) -> None:
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")


def _node(repo: Path) -> None:
    (repo / "package.json").write_text('{"name":"w","scripts":{"test":"vitest"}}', encoding="utf-8")
    (repo / "package-lock.json").write_text("{}", encoding="utf-8")


def _append_jobs(repo: Path, text: str) -> None:
    path = repo / CI
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _step_names(job: dict) -> list[str]:
    return [str(s.get("name")) for s in job["steps"] if s.get("name")]


def test_single_to_multi_language_replaces_the_old_test_job(tmp_path: Path):
    _python(tmp_path)
    doc, _ = _generate(tmp_path)
    assert list(doc["jobs"]) == ["test"]
    _append_jobs(
        tmp_path,
        "  deploy:\n    needs: test\n    runs-on: ubuntu-latest\n    steps:\n      - run: ./deploy.sh\n",
    )

    _node(tmp_path)
    doc, out = _generate(tmp_path)

    assert list(doc["jobs"]) == ["test-node", "test-python", "deploy"]
    python_runs = [job for job in doc["jobs"].values() if "Run tests (python)" in _step_names(job)]
    assert len(python_runs) == 1
    # The custom job now waits for the renamed job instead of one that no longer exists.
    assert doc["jobs"]["deploy"]["needs"] == "test-python"
    assert "jobs.test: renamed to jobs.test-python" in out
    assert "jobs.deploy.needs: 'test' -> 'test-python'" in out


def test_multi_to_single_language_renames_back_and_removes_the_stale_job(tmp_path: Path):
    _python(tmp_path)
    _node(tmp_path)
    doc, _ = _generate(tmp_path)
    assert list(doc["jobs"]) == ["test-node", "test-python"]
    _append_jobs(
        tmp_path,
        "  deploy:\n    needs: [test-node, test-python]\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: ./deploy.sh\n",
    )

    (tmp_path / "package.json").unlink()
    (tmp_path / "package-lock.json").unlink()
    doc, out = _generate(tmp_path)

    assert list(doc["jobs"]) == ["test", "deploy"]
    assert "Run tests (python)" in _step_names(doc["jobs"]["test"])
    assert doc["jobs"]["deploy"]["needs"] == ["test"]
    assert "jobs.test-python: renamed to jobs.test" in out
    assert "jobs.test-node: removed" in out

    # Settled: a further run changes nothing and reports nothing.
    before = (tmp_path / CI).read_text(encoding="utf-8")
    _, out = _generate(tmp_path)
    assert (tmp_path / CI).read_text(encoding="utf-8") == before
    assert "renamed or no longer needed" not in out


def test_custom_steps_in_a_renamed_job_are_carried_over(tmp_path: Path):
    _python(tmp_path)
    _generate(tmp_path)
    path = tmp_path / CI
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "      - name: Run tests (python)\n",
            "      # @heurix:preserve\n      - name: Lint\n        run: ruff check .\n      - name: Run tests (python)\n",
        ),
        encoding="utf-8",
    )

    _node(tmp_path)
    doc, _ = _generate(tmp_path)

    assert "test" not in doc["jobs"]
    assert "Lint" in _step_names(doc["jobs"]["test-python"])
    assert "@heurix:preserve\n      - name: Lint" in path.read_text(encoding="utf-8")


def test_custom_and_preserved_jobs_with_generated_looking_names_are_kept(tmp_path: Path):
    _python(tmp_path)
    _generate(tmp_path)
    text = (tmp_path / CI).read_text(encoding="utf-8")
    test_job = text[text.index("  test:\n") :]
    # A copy of the generated job with a different test command (still Python, still generated).
    integration = test_job.replace("  test:\n", "  test-integration:\n").replace(
        "run: python -m pytest", "run: python -m pytest tests/integration"
    )
    # A job marked preserved on its key.
    pinned = test_job.replace("  test:\n", "  # @heurix:preserve\n  test-legacy:\n")
    _append_jobs(tmp_path, integration + pinned)

    _node(tmp_path)
    doc, _ = _generate(tmp_path)

    assert set(doc["jobs"]) == {"test-node", "test-python", "test-integration", "test-legacy"}
    assert "@heurix:preserve\n  test-legacy:" in (tmp_path / CI).read_text(encoding="utf-8")


def test_stale_job_with_a_preserved_step_is_not_removed():
    existing = """\
jobs:
  test-node:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
      # @heurix:preserve
      - name: Run tests (node)
        run: npm test
  test-python:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
      - name: Run tests (python)
        run: python -m pytest
"""
    new = """\
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
      - name: Run tests (python)
        run: python -m pytest
"""
    merger = SmartMerger()
    doc = YAML(typ="safe").load(merger.merge_yaml(existing, new))

    assert list(doc["jobs"]) == ["test", "test-node"]
    assert merger.retired == ["jobs.test-python: renamed to jobs.test (your changes to it are carried over)"]


def test_jobs_without_heurix_test_steps_are_never_retired():
    existing = """\
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make test
"""
    new = """\
jobs:
  test-node:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
      - name: Run tests (node)
        run: npm test
"""
    merger = SmartMerger()
    doc = YAML(typ="safe").load(merger.merge_yaml(existing, new))

    assert list(doc["jobs"]) == ["test-node", "test"]
    assert merger.retired == []
