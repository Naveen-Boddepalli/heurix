"""
Workflow security audit (`hx check --security`).

Static checks over every workflow in `.github/workflows/`, covering the issues GitHub's security
hardening guide and its 2026 Actions changes call out. Rule IDs match the equivalent zizmor audits,
so a finding can be looked up, and silenced, the same way in both tools:

- `excessive-permissions`: `write-all`, or jobs that run with the default token permissions.
- `unpinned-uses`: third-party actions and reusable workflows not pinned to a commit SHA
  (workflows covered by `.github/workflows/actions.lock` are pinned there instead).
- `dangerous-triggers`: `pull_request_target` and `workflow_run`, which run with secrets and a
  write token on events that outside contributors can cause.
- `untrusted-checkout`: checking out pull request code in one of those workflows.
- `template-injection`: attacker-controlled `${{ github.event... }}` values expanded into a
  `run:` script or an `actions/github-script` script.
- `artipacked`: `actions/checkout` without `persist-credentials: false`.
- `secrets-inherit`: reusable workflow calls that pass every secret.

Silence a finding with `# hx: ignore[rule-id]` (or zizmor's `# zizmor: ignore[rule-id]`) on the
flagged line.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from heurix.core.drift import DriftFinding
from heurix.core.lockfile import LOCK_COMMAND, LockfileError, is_remote_action, load_lockfile
from heurix.core.pinning import workflow_files

# Owners whose actions GitHub maintains. Like zizmor's default `unpinned-uses` policy, this
# accepts a tag for these and asks for a SHA for everything else.
FIRST_PARTY_OWNERS = frozenset({"actions", "github", "dependabot"})

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_IGNORE_RE = re.compile(r"#.*\b(?:hx|zizmor):\s*ignore\[([^\]]*)\]")

# Values an outside contributor controls (GitHub's "untrusted input" list, plus the workflow_run
# and discussion equivalents). Indexes such as `commits[0]` or `pages.*` are normalised first.
_UNTRUSTED_CONTEXTS = [
    re.compile(p)
    for p in (
        r"\bgithub\.head_ref\b",
        r"\bgithub\.event\.(?:issue|pull_request|discussion)\.(?:title|body)\b",
        r"\bgithub\.event\.(?:comment|review|review_comment)\.body\b",
        r"\bgithub\.event\.pages\.\*\.page_name\b",
        r"\bgithub\.event\.(?:workflow_run\.)?head_commit\.(?:message|author\.(?:email|name))\b",
        r"\bgithub\.event\.commits\.\*\.(?:message|author\.(?:email|name))\b",
        r"\bgithub\.event\.pull_request\.head\.(?:ref|label|repo\.default_branch)\b",
        r"\bgithub\.event\.workflow_run\.(?:head_branch|display_title)\b",
    )
]
_INDEX_RE = re.compile(r"\[[^\]]*\]")

# Expressions in a checkout `ref:` / `repository:` that select the pull request's own code.
_PR_HEAD_RE = re.compile(
    r"github\.event\.pull_request\.head\.|github\.head_ref|github\.event\.workflow_run\.head_|"
    r"refs/pull/|github\.event\.number|github\.event\.pull_request\.number|merge_commit_sha"
)

_DANGEROUS_TRIGGERS = ("pull_request_target", "workflow_run")

# rule ID -> (default severity, one-line description). Used for SARIF rule metadata and the docs.
RULES: dict[str, tuple[str, str]] = {
    "excessive-permissions": ("WARNING", "Workflow or job token has more permissions than it needs"),
    "unpinned-uses": ("WARNING", "Third-party action or reusable workflow not pinned to a commit SHA"),
    "dangerous-triggers": ("WARNING", "Workflow uses pull_request_target or workflow_run"),
    "untrusted-checkout": ("ERROR", "Pull request code checked out in a privileged workflow"),
    "template-injection": ("ERROR", "Attacker-controlled expression expanded into a script"),
    "artipacked": ("WARNING", "actions/checkout keeps the job token in .git/config"),
    "secrets-inherit": ("WARNING", "Reusable workflow call passes every secret"),
}


def _line_of_key(node: Any, key: str) -> int | None:
    lc = getattr(node, "lc", None)
    try:
        return int(lc.key(key)[0]) + 1 if lc is not None else None
    except Exception:
        return None


def _line_of_node(node: Any) -> int | None:
    lc = getattr(node, "lc", None)
    return int(lc.line) + 1 if lc is not None and lc.line is not None else None


def _triggers(doc: Mapping[str, Any]) -> list[str]:
    # YAML 1.1 loaders may read a bare `on:` key as True.
    on = doc.get("on", doc.get(True))  # type: ignore[call-overload]
    if isinstance(on, str):
        return [on]
    if isinstance(on, Mapping):
        return [str(k) for k in on]
    if isinstance(on, Sequence):
        return [str(t) for t in on]
    return []


def _untrusted_refs(text: str) -> list[str]:
    """Attacker-controlled contexts used inside `${{ }}` expressions in `text`."""
    found: list[str] = []
    for match in _EXPR_RE.finditer(text):
        expr = _INDEX_RE.sub(".*", match.group(1)).replace("..", ".")
        for pattern in _UNTRUSTED_CONTEXTS:
            for hit in pattern.finditer(expr):
                ref = hit.group(0)
                if ref not in found:
                    found.append(ref)
    return found


def _steps(job: Mapping[str, Any]) -> Iterator[tuple[int, Mapping[str, Any]]]:
    steps = job.get("steps")
    if isinstance(steps, Sequence) and not isinstance(steps, str):
        for i, step in enumerate(steps):
            if isinstance(step, Mapping):
                yield i, step


def _step_label(job_id: str, index: int, step: Mapping[str, Any]) -> str:
    name = step.get("name")
    return f"jobs.{job_id}.steps[{index}]" + (f" ({name})" if isinstance(name, str) and name else "")


def _action_name(uses: str) -> str:
    return uses.split("@", 1)[0].lower()


class _Audit:
    def __init__(self, rel_path: str, doc: Mapping[str, Any], locked: bool) -> None:
        self.rel_path = rel_path
        self.doc = doc
        self.locked = locked
        self.findings: list[DriftFinding] = []

    def add(self, rule_id: str, severity: str, line: int | None, issue: str, recommendation: str) -> None:
        self.findings.append(DriftFinding(self.rel_path, issue, severity, recommendation, rule_id, line))

    def run(self) -> list[DriftFinding]:
        jobs = self.doc.get("jobs")
        if not isinstance(jobs, Mapping):
            return self.findings
        triggers = _triggers(self.doc)
        self._permissions(jobs)
        self._dangerous_triggers(triggers)
        for job_id, job in jobs.items():
            if not isinstance(job, Mapping):
                continue
            self._reusable_call(str(job_id), job)
            for index, step in _steps(job):
                self._step(str(job_id), index, step, triggers)
        return self.findings

    def _permissions(self, jobs: Mapping[str, Any]) -> None:
        workflow_perms = self.doc.get("permissions")
        if workflow_perms == "write-all":
            self.add(
                "excessive-permissions",
                "ERROR",
                _line_of_key(self.doc, "permissions"),
                "The workflow grants 'permissions: write-all' to every job.",
                "Set 'permissions: contents: read' and give each job that writes only the scopes it needs.",
            )
        for job_id, job in jobs.items():
            if isinstance(job, Mapping) and job.get("permissions") == "write-all":
                self.add(
                    "excessive-permissions",
                    "ERROR",
                    _line_of_key(job, "permissions"),
                    f"jobs.{job_id} grants 'permissions: write-all'.",
                    "List only the scopes the job needs, for example 'contents: write'.",
                )
        if workflow_perms is not None:
            return
        # Reusable workflow calls take the caller's permissions, so they count as uncovered too.
        uncovered = [str(j) for j, job in jobs.items() if isinstance(job, Mapping) and "permissions" not in job]
        if uncovered:
            self.add(
                "excessive-permissions",
                "WARNING",
                _line_of_key(self.doc, "jobs"),
                f"No 'permissions' block, so {', '.join(uncovered)} run(s) with the repository's default token "
                "permissions, which may include write access.",
                "Add 'permissions: contents: read' at the top of the workflow, and grant more per job only "
                "where needed ([ci] harden = true adds it to Heurix's ci.yml).",
            )

    def _dangerous_triggers(self, triggers: list[str]) -> None:
        for trigger in triggers:
            if trigger in _DANGEROUS_TRIGGERS:
                on_node = self.doc.get("on", self.doc.get(True))  # type: ignore[call-overload]
                line = _line_of_key(on_node, trigger) if isinstance(on_node, Mapping) else None
                self.add(
                    "dangerous-triggers",
                    "WARNING",
                    line or _line_of_key(self.doc, "on"),
                    f"'{trigger}' runs with repository secrets and a write token on events outside "
                    "contributors can trigger.",
                    "Use 'pull_request' where possible. If you need this trigger, never check out or run code "
                    "from the pull request, and keep permissions minimal.",
                )

    def _reusable_call(self, job_id: str, job: Mapping[str, Any]) -> None:
        uses = job.get("uses")
        if is_remote_action(uses):
            self._pin(str(uses), _line_of_key(job, "uses"), f"jobs.{job_id}")
        if job.get("secrets") == "inherit":
            self.add(
                "secrets-inherit",
                "WARNING",
                _line_of_key(job, "secrets"),
                f"jobs.{job_id} passes every repository secret to {uses or 'a reusable workflow'}.",
                "Pass only the secrets the called workflow uses under 'secrets:'.",
            )

    def _step(self, job_id: str, index: int, step: Mapping[str, Any], triggers: list[str]) -> None:
        label = _step_label(job_id, index, step)
        uses = step.get("uses")
        if is_remote_action(uses):
            self._pin(str(uses), _line_of_key(step, "uses"), label)

        scripts: list[tuple[str, int | None]] = []
        run = step.get("run")
        if isinstance(run, str):
            scripts.append((run, _line_of_key(step, "run")))
        with_ = step.get("with")
        action = _action_name(uses) if isinstance(uses, str) else ""
        if action == "actions/github-script" and isinstance(with_, Mapping) and isinstance(with_.get("script"), str):
            scripts.append((with_["script"], _line_of_key(with_, "script")))
        for text, line in scripts:
            refs = _untrusted_refs(text)
            if refs:
                self.add(
                    "template-injection",
                    "ERROR",
                    line or _line_of_node(step),
                    f"{label} expands {', '.join(refs)} into a script; a crafted value can run arbitrary "
                    "commands with the job's token and secrets.",
                    "Pass the value through 'env:' (for example 'TITLE: ${{ github.event.issue.title }}') and "
                    'use "$TITLE" in the script.',
                )

        if action == "actions/checkout":
            opts = with_ if isinstance(with_, Mapping) else {}
            if str(opts.get("persist-credentials", "")).lower() != "false":
                self.add(
                    "artipacked",
                    "WARNING",
                    _line_of_key(step, "uses") or _line_of_node(step),
                    f"{label} leaves the job token in .git/config, where later steps and uploaded "
                    "artifacts can read it.",
                    "Add 'with: persist-credentials: false' unless a later step pushes with the token.",
                )
            selector = f"{opts.get('ref', '')} {opts.get('repository', '')}"
            if any(t in _DANGEROUS_TRIGGERS for t in triggers) and _PR_HEAD_RE.search(selector):
                self.add(
                    "untrusted-checkout",
                    "ERROR",
                    _line_of_key(opts, "ref") or _line_of_key(step, "uses"),
                    f"{label} checks out pull request code in a workflow that has secrets and a write token.",
                    "Build untrusted code in a 'pull_request' workflow instead, and pass results to this one "
                    "as artifacts.",
                )

    def _pin(self, uses: str, line: int | None, where: str) -> None:
        action, _, ref = uses.partition("@")
        if self.locked or _SHA_RE.match(ref) or action.split("/", 1)[0].lower() in FIRST_PARTY_OWNERS:
            return
        self.add(
            "unpinned-uses",
            "WARNING",
            line,
            f"{where} uses {uses}, a tag or branch its owner can move to different code.",
            f"Pin it to a commit SHA with 'hx pin', or lock the workflow with '{LOCK_COMMAND}'.",
        )


def _ignored(finding: DriftFinding, lines: list[str]) -> bool:
    if finding.line is None or not 0 < finding.line <= len(lines):
        return False
    match = _IGNORE_RE.search(lines[finding.line - 1])
    if not match:
        return False
    rules = {r.strip() for r in match.group(1).split(",")}
    return finding.rule_id in rules


def audit_workflows(repo_root: str | Path) -> list[DriftFinding]:
    """Security findings for every workflow under `.github/workflows/`."""
    root = Path(repo_root)
    try:
        lock = load_lockfile(root)
    except LockfileError:
        lock = None  # `hx check` reports the unreadable lockfile itself.
    yaml = YAML()
    findings: list[DriftFinding] = []
    for path in workflow_files(root):
        rel_path = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            doc = yaml.load(text)
        except Exception:
            continue  # Malformed YAML is reported by the drift checks.
        if not isinstance(doc, Mapping):
            continue
        lines = text.splitlines()
        audit = _Audit(rel_path, doc, locked=bool(lock and lock.covers(rel_path)))
        findings.extend(f for f in audit.run() if not _ignored(f, lines))
    return findings
