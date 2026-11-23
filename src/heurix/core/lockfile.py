"""
GitHub Actions workflow lockfile support (`.github/workflows/actions.lock`).

`gh actions-lock` writes the lockfile. Every action used by a workflow listed under `workflows:`
("onboarded") must have an entry, or the run fails at job start. Heurix only reads the file: it
never resolves or writes pins itself, because doing that needs the network and GitHub's own
provenance checks. The format is still pre-1.0 (`version: 'v0.0.3'` at the time of writing), so
reading is deliberately lenient: only the `workflows` map is relied on.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

LOCKFILE_PATH = ".github/workflows/actions.lock"
LOCK_COMMAND = "gh actions-lock"

# owner/repo[/path]@ref. Local (`./`, `$/`), `docker://` and expression refs are excluded.
_REMOTE_USES_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\s]+)?@[^\s@]+$")


class LockfileError(ValueError):
    """Raised when actions.lock exists but cannot be read as a lockfile."""


@dataclass
class WorkflowLock:
    version: str | None
    # workflow path (".github/workflows/ci.yml") -> dependency keys ("actions/checkout@v7.0.1")
    workflows: dict[str, set[str]] = field(default_factory=dict)

    def covers(self, workflow_path: str) -> bool:
        return _norm_path(workflow_path) in self.workflows

    def locked_refs(self, workflow_path: str) -> dict[str, str]:
        """Map each action (lowercased `owner/repo[/path]`) locked for this workflow to its ref.

        When an action is locked at several refs, the highest version tag wins.
        """
        best: dict[str, str] = {}
        for key in sorted(self.workflows.get(_norm_path(workflow_path), set())):
            action, _, ref = key.partition("@")
            if not ref:
                continue
            current = best.get(action)
            if current is None or _ref_sort_key(ref) > _ref_sort_key(current):
                best[action] = ref
        return best

    def missing(self, workflow_path: str, uses_refs: Sequence[str]) -> list[str]:
        """Return the `uses:` refs in `workflow_path` that have no entry in the lockfile."""
        locked = self.workflows.get(_norm_path(workflow_path), set())
        out: list[str] = []
        for ref in uses_refs:
            if _dependency_key(ref) not in locked and ref not in out:
                out.append(ref)
        return out


def _ref_sort_key(ref: str) -> tuple[int, tuple[int, ...]]:
    """Order version tags (`v7`, `v7.0.1`) above other refs, and higher versions above lower."""
    match = re.match(r"^v?(\d+(?:\.\d+)*)$", ref)
    return (1, tuple(int(p) for p in match.group(1).split("."))) if match else (0, ())


def _norm_path(path: str) -> str:
    path = path.replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def _dependency_key(uses: str) -> str:
    """Lockfile keys are `owner/repo@ref`; owner and repo are case-insensitive on GitHub."""
    action, _, ref = uses.partition("@")
    return f"{action.lower()}@{ref}"


def is_remote_action(uses: Any) -> bool:
    """True for a `uses:` value the lockfile pins: a remote `owner/repo[/path]@ref` action."""
    return isinstance(uses, str) and "${{" not in uses and bool(_REMOTE_USES_RE.match(uses.strip()))


def load_lockfile(repo_root: str | Path) -> WorkflowLock | None:
    """Read `.github/workflows/actions.lock`; None when the repository has no lockfile."""
    path = Path(repo_root) / LOCKFILE_PATH
    if not path.is_file():
        return None
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        raise LockfileError(f"{LOCKFILE_PATH} is not valid YAML: {e}") from e
    if not isinstance(data, Mapping) or not isinstance(data.get("workflows"), Mapping):
        raise LockfileError(f"{LOCKFILE_PATH} has no 'workflows' map; it may use a newer lockfile format.")
    workflows: dict[str, set[str]] = {}
    for wf_path, deps in data["workflows"].items():
        if not isinstance(wf_path, str):
            continue
        keys = {_dependency_key(d) for d in deps if isinstance(d, str)} if isinstance(deps, Sequence) else set()
        workflows[_norm_path(wf_path)] = keys
    version = data.get("version")
    return WorkflowLock(version=str(version) if version is not None else None, workflows=workflows)


def workflow_action_refs(doc: Any) -> list[str]:
    """Remote action refs used by steps in a parsed workflow, in order and without duplicates.

    Job-level `uses:` (reusable workflow calls) is skipped: `gh actions-lock` doesn't lock those.
    """
    refs: list[str] = []
    jobs = doc.get("jobs") if isinstance(doc, Mapping) else None
    if not isinstance(jobs, Mapping):
        return refs
    for job in jobs.values():
        steps = job.get("steps") if isinstance(job, Mapping) else None
        if not isinstance(steps, Sequence) or isinstance(steps, str):
            continue
        for step in steps:
            uses = step.get("uses") if isinstance(step, Mapping) else None
            if is_remote_action(uses):
                ref = str(uses).strip()
                if ref not in refs:
                    refs.append(ref)
    return refs
