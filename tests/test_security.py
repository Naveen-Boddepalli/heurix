"""
Tests for the workflow security audit (`hx check --security`) and JSON/SARIF reports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from heurix.cli import app
from heurix.core.security import RULES, audit_workflows

SHA = "0123456789abcdef0123456789abcdef01234567"


def _workflow(root: Path, text: str, name: str = "ci.yml") -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / name).write_text(text, encoding="utf-8")


def _rules(root: Path) -> list[tuple[str, int | None]]:
    return [(f.rule_id, f.line) for f in audit_workflows(root)]


CLEAN = f"""name: CI
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@{SHA}  # v10.4.0
      - name: Greet
        env:
          TITLE: ${{{{ github.event.pull_request.title }}}}
        run: echo "$TITLE" ${{{{ github.sha }}}}
"""


def test_a_hardened_workflow_has_no_findings(tmp_path: Path):
    _workflow(tmp_path, CLEAN)

    assert audit_workflows(tmp_path) == []


def test_permissions_findings(tmp_path: Path):
    _workflow(
        tmp_path,
        """on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps: [{run: make}]
  release:
    runs-on: ubuntu-latest
    permissions: write-all
    steps: [{run: make release}]
""",
    )
    _workflow(tmp_path, "on: push\npermissions: write-all\njobs:\n  a:\n    runs-on: x\n    steps: []\n", "all.yml")

    findings = audit_workflows(tmp_path)

    assert [(f.file_path.rsplit("/", 1)[1], f.rule_id, f.severity, f.line) for f in findings] == [
        ("all.yml", "excessive-permissions", "ERROR", 2),
        ("ci.yml", "excessive-permissions", "ERROR", 8),
        ("ci.yml", "excessive-permissions", "WARNING", 2),
    ]
    # Only the job without its own block runs with the default token.
    assert "build run(s)" in findings[2].issue


def test_unpinned_uses_covers_third_party_steps_and_reusable_workflows(tmp_path: Path):
    _workflow(
        tmp_path,
        f"""on: push
permissions: {{}}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v7
      - uses: github/codeql-action/init@v4
      - uses: docker/login-action@v4
      - uses: Swatinem/rust-cache@{SHA}
      - uses: ./local-action
      - uses: docker://alpine:3.20
  shared:
    uses: octo-org/workflows/.github/workflows/ci.yml@main
""",
    )

    assert _rules(tmp_path) == [("unpinned-uses", 9), ("unpinned-uses", 14)]


def test_locked_workflows_are_pinned_by_the_lockfile(tmp_path: Path):
    _workflow(tmp_path, "on: push\npermissions: {}\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: o/a@v1\n")
    (tmp_path / ".github/workflows/actions.lock").write_text(
        "version: 'v0.0.3'\nworkflows:\n  '.github/workflows/ci.yml':\n    - 'o/a@v1'\n", encoding="utf-8"
    )

    assert audit_workflows(tmp_path) == []


def test_template_injection_in_run_and_github_script(tmp_path: Path):
    _workflow(
        tmp_path,
        """on: issues
permissions: {}
jobs:
  triage:
    runs-on: ubuntu-latest
    steps:
      - name: Echo title
        run: |
          echo "${{ github.event.issue.title }}"
          echo "${{ github.event.commits[0].message }} ${{github.head_ref}}"
      - uses: actions/github-script@v8
        with:
          script: console.log("${{ github.event.comment.body }}")
      - run: echo "${{ github.event.issue.number }} ${{ github.actor }}"
""",
    )

    findings = audit_workflows(tmp_path)

    assert [(f.rule_id, f.line) for f in findings] == [("template-injection", 8), ("template-injection", 13)]
    assert "github.event.issue.title, github.event.commits.*.message, github.head_ref" in findings[0].issue
    assert "Echo title" in findings[0].issue
    assert all(f.severity == "ERROR" for f in findings)


def test_dangerous_triggers_and_untrusted_checkout(tmp_path: Path):
    _workflow(
        tmp_path,
        """on:
  pull_request_target:
    types: [opened]
permissions:
  contents: read
jobs:
  label:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
          ref: ${{ github.event.pull_request.head.sha }}
""",
    )
    # The same checkout under a plain pull_request trigger is fine.
    _workflow(
        tmp_path,
        "on: pull_request\npermissions: {}\njobs:\n  t:\n    runs-on: x\n    steps:\n"
        "      - uses: actions/checkout@v7\n        with:\n          persist-credentials: false\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n",
        "pr.yml",
    )

    assert _rules(tmp_path) == [("dangerous-triggers", 2), ("untrusted-checkout", 13)]


def test_artipacked_and_secrets_inherit(tmp_path: Path):
    _workflow(
        tmp_path,
        """on: push
permissions: {}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/checkout@v7
        with:
          persist-credentials: true
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
  deploy:
    uses: ./.github/workflows/deploy.yml
    secrets: inherit
""",
    )

    assert _rules(tmp_path) == [("artipacked", 7), ("artipacked", 8), ("secrets-inherit", 16)]


def test_ignore_comments_silence_one_rule_on_one_line(tmp_path: Path):
    _workflow(
        tmp_path,
        """on: push
permissions: {}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7  # hx: ignore[artipacked]
      - uses: docker/login-action@v4  # zizmor: ignore[unpinned-uses, artipacked]
      - uses: docker/build-push-action@v7  # hx: ignore[artipacked]
""",
    )

    assert _rules(tmp_path) == [("unpinned-uses", 9)]


def test_malformed_or_non_workflow_files_are_skipped(tmp_path: Path):
    _workflow(tmp_path, "jobs: [unclosed\n")
    _workflow(tmp_path, "- a list\n", "list.yml")
    _workflow(tmp_path, "name: no jobs\n", "empty.yaml")

    assert audit_workflows(tmp_path) == []


def _hardened_repo(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    assert CliRunner().invoke(app, ["generate", "--path", str(tmp_path), "--yes", "--no-explain"]).exit_code == 0
    return tmp_path


def test_check_security_text_report(tmp_path: Path):
    repo = _hardened_repo(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["check", "--path", str(repo), "--security"]).exit_code == 0

    _workflow(repo, "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: o/a@v1\n", "extra.yml")
    result = runner.invoke(app, ["check", "--path", str(repo), "--security"])

    assert result.exit_code == 1
    out = " ".join(result.stdout.split())
    assert "Security Findings (2 issue(s))" in out
    assert ".github/workflows/extra.yml:6:" in out
    assert "[unpinned-uses]" in out
    assert "Drift Detected" not in out
    # Without --security the extra workflow is not audited.
    assert runner.invoke(app, ["check", "--path", str(repo)]).exit_code == 0


def test_check_json_report_is_clean_json_on_stdout(tmp_path: Path):
    repo = _hardened_repo(tmp_path)
    (repo / "vercel.json").write_text("[]", encoding="utf-8")  # the scan ignores it with a warning
    _workflow(
        repo, "on: push\npermissions: {}\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: o/a@v1\n", "x.yml"
    )

    result = CliRunner().invoke(app, ["check", "--path", str(repo), "--security", "--format", "json"])

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["tool"] == "heurix"
    assert report["summary"] == {"total": 1, "errors": 0, "warnings": 1}
    assert report["findings"] == [
        {
            "rule_id": "unpinned-uses",
            "severity": "WARNING",
            "file": ".github/workflows/x.yml",
            "line": 7,
            "issue": report["findings"][0]["issue"],
            "recommendation": "Pin it to a commit SHA with 'hx pin', or lock the workflow with 'gh actions-lock'.",
        }
    ]
    assert "vercel.json" in result.stderr


def test_check_sarif_report(tmp_path: Path):
    repo = _hardened_repo(tmp_path)
    (repo / ".github/workflows/ci.yml").unlink()  # a drift finding with no line
    _workflow(
        repo,
        "on: issues\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: echo ${{ github.event.issue.body }}\n",
        "triage.yml",
    )

    result = CliRunner().invoke(app, ["check", "--path", str(repo), "--security", "-f", "sarif"])

    assert result.exit_code == 1
    sarif = json.loads(result.stdout)
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    rules = {r["id"]: r for r in run["tool"]["driver"]["rules"]}
    assert set(rules) == {"drift", "excessive-permissions", "template-injection"}
    assert rules["template-injection"]["properties"] == {"tags": ["security"], "security-severity": "8.0"}
    assert rules["drift"]["properties"] == {"tags": ["ci"]}
    by_rule = {r["ruleId"]: r for r in run["results"]}
    injection = by_rule["template-injection"]
    assert injection["level"] == "error"
    assert run["tool"]["driver"]["rules"][injection["ruleIndex"]]["id"] == "template-injection"
    location = injection["locations"][0]["physicalLocation"]
    assert location == {
        "artifactLocation": {"uri": ".github/workflows/triage.yml", "uriBaseId": "%SRCROOT%"},
        "region": {"startLine": 6},
    }
    assert by_rule["drift"]["locations"][0]["physicalLocation"]["region"] == {"startLine": 1}


def test_check_rejects_unknown_formats(tmp_path: Path):
    result = CliRunner().invoke(app, ["check", "--path", str(tmp_path), "--format", "xml"])

    assert result.exit_code == 2
    assert "Unknown --format 'xml'" in result.stderr


@pytest.mark.parametrize(
    "files",
    [
        {"pyproject.toml": '[project]\nname="a"\nversion="0.1"\ndependencies=["psycopg2"]\n', "uv.lock": ""},
        {"package.json": '{"name":"w","scripts":{"test":"vitest","lint":"eslint ."}}', "pnpm-lock.yaml": ""},
        {"Cargo.toml": '[package]\nname="r"\nversion="0.1.0"\n', "Cargo.lock": ""},
        {"go.mod": "module x\n\ngo 1.23\n", ".golangci.yml": ""},
        {"CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject(x)\n"},
        {"requirements.txt": "flask\n", "Dockerfile": "FROM python:3.12\n", ".env.example": "API_KEY=\n"},
        {
            "package.json": '{"name":"f","scripts":{"test":"jest"}}',
            "package-lock.json": "{}",
            "firebase.json": '{"hosting":{}}',
            ".firebaserc": '{"projects":{"default":"p"}}',
        },
    ],
    ids=["uv", "pnpm", "rust", "go", "cpp", "docker", "firebase"],
)
def test_generated_workflows_only_need_pinning(tmp_path: Path, files: dict[str, str]):
    """Heurix's own output is clean apart from third-party tags, which 'hx pin' resolves."""
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert CliRunner().invoke(app, ["generate", "--path", str(tmp_path), "--yes", "--no-explain"]).exit_code == 0

    findings = audit_workflows(tmp_path)

    assert [f for f in findings if f.rule_id != "unpinned-uses"] == []


def test_every_rule_has_metadata():
    assert all(severity in {"ERROR", "WARNING"} and text for severity, text in RULES.values())
