"""
Tests for `hx pin` (rewriting workflow action refs to commit SHAs). The network is never used:
`git ls-remote` is replaced with a fake that answers from a fixed table.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from heurix.cli import app
from heurix.core import pinning
from heurix.core.pinning import PinError, PinResult, RefResolver, git_ls_remote, pin_text

TAG_OBJECT = "1" * 40
CHECKOUT = "a" * 40
SETUP_PY = "b" * 40
CODEQL = "c" * 40
BRANCH = "d" * 40

REMOTE = {
    "actions/checkout": {"refs/tags/v7": TAG_OBJECT, "refs/tags/v7^{}": CHECKOUT},
    "actions/setup-python": {"refs/tags/v7.1.0": SETUP_PY},
    "github/codeql-action": {"refs/tags/v4": CODEQL},
    "octo/tool": {"refs/heads/main": BRANCH, "refs/heads/feature/main": "e" * 40},
}


class FakeRemote:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, repo: str, ref: str) -> dict[str, str]:
        self.calls.append((repo, ref))
        if repo.lower() not in REMOTE:
            raise PinError(f"could not read github.com/{repo}: repository not found")
        return REMOTE[repo.lower()]


WORKFLOW = """name: CI
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Python
        uses: "actions/setup-python@v7.1.0"   # pinned for 3.12
      - uses: github/codeql-action/init@v4 # v4
      - uses: Actions/Checkout@v7
      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567  # v6
      - uses: ./local-action
      - uses: docker://alpine:3.20
      - uses: dtolnay/rust-toolchain@stable
      - uses: octo/tool@main
      - uses: ${{ matrix.action }}
      - run: echo "uses: not/a-step@v1"
"""


def test_pin_text_rewrites_remote_refs_and_keeps_everything_else():
    remote = FakeRemote()
    result = PinResult()

    out = pin_text(WORKFLOW, ".github/workflows/ci.yml", RefResolver(remote), result)

    assert out.splitlines() == [
        "name: CI",
        "on: push",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        # The peeled commit, not the annotated tag object.
        f"      - uses: actions/checkout@{CHECKOUT}  # v7",
        "      - name: Python",
        f'        uses: "actions/setup-python@{SETUP_PY}"  # v7.1.0 pinned for 3.12',
        # An existing comment that already names the ref isn't repeated.
        f"      - uses: github/codeql-action/init@{CODEQL}  # v4",
        f"      - uses: Actions/Checkout@{CHECKOUT}  # v7",
        "      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567  # v6",
        "      - uses: ./local-action",
        "      - uses: docker://alpine:3.20",
        "      - uses: dtolnay/rust-toolchain@stable",
        f"      - uses: octo/tool@{BRANCH}  # main",
        "      - uses: ${{ matrix.action }}",
        '      - run: echo "uses: not/a-step@v1"',
    ]
    assert [(c.line, c.action, c.ref) for c in result.changes] == [
        (7, "actions/checkout", "v7"),
        (9, "actions/setup-python", "v7.1.0"),
        (10, "github/codeql-action/init", "v4"),
        (11, "Actions/Checkout", "v7"),
        (16, "octo/tool", "main"),
    ]
    assert [(line, reason.split(":")[0]) for _, line, reason in result.skipped] == [
        (15, "dtolnay/rust-toolchain@stable")
    ]
    assert result.failures == []
    # Resolved once per repository and ref, whatever the case of owner/repo.
    assert remote.calls.count(("actions/checkout", "v7")) == 1
    assert len(remote.calls) == 4


def test_pin_text_keeps_crlf_line_endings():
    result = PinResult()
    out = pin_text("steps:\r\n  - uses: actions/checkout@v7\r\n", "ci.yml", RefResolver(FakeRemote()), result)

    assert out == f"steps:\r\n  - uses: actions/checkout@{CHECKOUT}  # v7\r\n"


def test_unresolvable_refs_are_reported_and_left_alone():
    result = PinResult()
    text = "    - uses: actions/checkout@v99\n    - uses: nobody/missing@v1\n"

    assert pin_text(text, "ci.yml", RefResolver(FakeRemote()), result) == text
    assert result.changes == []
    assert [error for _, _, error in result.failures] == [
        "actions/checkout@v99: github.com/actions/checkout has no tag or branch named 'v99'",
        "nobody/missing@v1: could not read github.com/nobody/missing: repository not found",
    ]


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_git_ls_remote_parses_refs_and_never_prompts(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs["env"]
        return _completed(0, f"{TAG_OBJECT}\trefs/tags/v7\n{CHECKOUT}\trefs/tags/v7^{{}}\n")

    monkeypatch.setattr(pinning.subprocess, "run", fake_run)

    assert git_ls_remote("actions/checkout", "v7") == {"refs/tags/v7": TAG_OBJECT, "refs/tags/v7^{}": CHECKOUT}
    assert seen["cmd"] == ["git", "ls-remote", "https://github.com/actions/checkout", "v7"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"  # type: ignore[index]


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (_completed(128, stderr="remote: Not Found\nfatal: repository not found\n"), "fatal: repository not found"),
        (subprocess.TimeoutExpired(cmd="git", timeout=30), "timed out after 30s"),
        (FileNotFoundError("git"), "git is not installed"),
    ],
)
def test_git_ls_remote_turns_failures_into_pin_errors(monkeypatch: pytest.MonkeyPatch, outcome, message: str):
    def fake_run(cmd, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(pinning.subprocess, "run", fake_run)

    with pytest.raises(PinError, match=message):
        git_ls_remote("actions/checkout", "v7")


def _repo(tmp_path: Path, workflow: str = "jobs:\n  t:\n    steps:\n      - uses: actions/checkout@v7\n") -> Path:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(workflow, encoding="utf-8")
    (wf / "notes.md").write_text("uses: actions/checkout@v7\n", encoding="utf-8")
    return wf


def test_pin_command_writes_pins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pinning, "git_ls_remote", FakeRemote())
    wf = _repo(tmp_path)

    preview = CliRunner().invoke(app, ["pin", "--path", str(tmp_path), "--dry-run"])
    assert preview.exit_code == 0
    assert "would pin 1 action ref(s) in 1 file(s)" in " ".join(preview.stdout.split())
    assert "@v7\n" in (wf / "ci.yml").read_text()

    result = CliRunner().invoke(app, ["pin", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (wf / "ci.yml").read_text().endswith(f"uses: actions/checkout@{CHECKOUT}  # v7\n")
    assert (wf / "notes.md").read_text() == "uses: actions/checkout@v7\n"

    again = CliRunner().invoke(app, ["pin", "--path", str(tmp_path)])
    assert again.exit_code == 0
    assert "already pinned" in again.stdout


def test_pin_command_fails_when_a_ref_cannot_be_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pinning, "git_ls_remote", FakeRemote())
    wf = _repo(tmp_path, "steps:\n  - uses: actions/checkout@v7\n  - uses: nobody/missing@v1\n")

    result = CliRunner().invoke(app, ["pin", "--path", str(tmp_path)])

    assert result.exit_code == 1
    out = " ".join(result.stdout.split())
    assert "nobody/missing@v1" in out
    assert "1 ref(s) could not be resolved" in out
    # Refs that did resolve are still written.
    assert f"actions/checkout@{CHECKOUT}" in (wf / "ci.yml").read_text()


def test_pin_command_defers_to_the_workflow_lockfile(tmp_path: Path):
    wf = _repo(tmp_path)
    (wf / "actions.lock").write_text("version: 'v0.0.3'\nworkflows: {}\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["pin", "--path", str(tmp_path)])

    assert result.exit_code == 1
    assert "gh actions-lock" in result.stdout
    assert "@v7\n" in (wf / "ci.yml").read_text()


def test_pin_command_without_workflows(tmp_path: Path):
    result = CliRunner().invoke(app, ["pin", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert "nothing to pin" in result.stdout
