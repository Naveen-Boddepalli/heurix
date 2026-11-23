"""
`hx pin`: rewrite workflow action refs to full commit SHAs.

`uses: actions/checkout@v7` becomes `uses: actions/checkout@<40-char sha>  # v7`. The trailing
`# v7` comment is what Dependabot and Renovate read to keep SHA pins up to date, and Heurix's
merger carries it through later `hx generate` runs.

Rewriting is line-based so comments, quoting and layout are left exactly as they were. Refs are
resolved with `git ls-remote` against github.com, which needs no token and has no API rate limit.
This is the only Heurix feature that uses the network, and it only runs when asked.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

WORKFLOWS_DIR = ".github/workflows"
LS_REMOTE_TIMEOUT_SECONDS = 30

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_USES_LINE_RE = re.compile(
    r"^(?P<lead>\s*(?:-\s+)?uses:[ \t]*)"
    r"(?P<quote>['\"]?)"
    r"(?P<action>(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[^@\s'\"#]+)?)"
    r"@(?P<ref>[^\s'\"#]+)"
    r"(?P=quote)"
    r"(?P<tail>[ \t]*(?:#[ \t]*(?P<comment>.*?))?)[ \t]*$"
)

# Actions whose ref is an input, not a version: a SHA ref would drop the input they need.
_REF_IS_INPUT = {
    "dtolnay/rust-toolchain": "its ref selects the toolchain; pin it with a SHA plus a 'toolchain:' input by hand",
}


class PinError(RuntimeError):
    """Raised when a ref cannot be resolved to a commit."""


LsRemote = Callable[[str, str], dict[str, str]]


def git_ls_remote(repo: str, ref: str) -> dict[str, str]:
    """Return `{refname: sha}` for refs on github.com/<repo> that match `ref`."""
    try:
        proc = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{repo}", ref],
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT_SECONDS,
            check=False,
            # Fail instead of prompting for credentials when a repository doesn't exist.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError as e:
        raise PinError("git is not installed or not on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise PinError(f"timed out after {LS_REMOTE_TIMEOUT_SECONDS}s reaching github.com/{repo}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise PinError(f"could not read github.com/{repo}: {detail[-1] if detail else 'git ls-remote failed'}")
    refs: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if sha and name:
            refs[name.strip()] = sha.strip()
    return refs


@dataclass
class RefResolver:
    """Resolve `owner/repo@ref` to a commit SHA, once per repository and ref."""

    # None means git_ls_remote, looked up at call time.
    ls_remote: LsRemote | None = None
    _cache: dict[tuple[str, str], str] = field(default_factory=dict)

    def resolve(self, repo: str, ref: str) -> str:
        key = (repo.lower(), ref)
        if key not in self._cache:
            refs = (self.ls_remote or git_ls_remote)(repo, ref)
            # An annotated tag's peeled entry (^{}) is the commit; the plain entry is the tag object.
            for name in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}"):
                if name in refs:
                    self._cache[key] = refs[name]
                    break
            else:
                raise PinError(f"github.com/{repo} has no tag or branch named '{ref}'")
        return self._cache[key]


@dataclass
class PinChange:
    file_path: str
    line: int
    action: str
    ref: str
    sha: str


@dataclass
class PinResult:
    changes: list[PinChange] = field(default_factory=list)
    skipped: list[tuple[str, int, str]] = field(default_factory=list)  # (file, line, reason)
    failures: list[tuple[str, int, str]] = field(default_factory=list)  # (file, line, error)
    updated_files: dict[str, str] = field(default_factory=dict)  # rel path -> new text


def workflow_files(repo_root: Path) -> list[Path]:
    wf_dir = repo_root / WORKFLOWS_DIR
    if not wf_dir.is_dir():
        return []
    return sorted(p for p in wf_dir.iterdir() if p.is_file() and p.suffix in {".yml", ".yaml"})


def pin_text(text: str, rel_path: str, resolver: RefResolver, result: PinResult) -> str:
    """Pin every remote `uses:` ref in one workflow's text; record what happened in `result`."""
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        match = _USES_LINE_RE.match(body)
        if not match or _SHA_RE.match(match["ref"]):
            out.append(line)
            continue
        action, ref, repo = match["action"], match["ref"], match["repo"]
        reason = _REF_IS_INPUT.get(repo.lower())
        if reason:
            result.skipped.append((rel_path, lineno, f"{action}@{ref}: {reason}"))
            out.append(line)
            continue
        try:
            sha = resolver.resolve(repo, ref)
        except PinError as e:
            result.failures.append((rel_path, lineno, f"{action}@{ref}: {e}"))
            out.append(line)
            continue
        comment = (match["comment"] or "").strip()
        # The ref leads the comment so Dependabot and Renovate can keep the pin updated.
        note = ref if not comment or comment.split()[0] == ref else f"{ref} {comment}"
        quote = match["quote"]
        out.append(f"{match['lead']}{quote}{action}@{sha}{quote}  # {note}{newline}")
        result.changes.append(PinChange(rel_path, lineno, action, ref, sha))
    return "".join(out)


def pin_workflows(repo_root: Path, resolver: RefResolver | None = None) -> PinResult:
    """Pin action refs in every workflow under `.github/workflows/`. Nothing is written to disk."""
    resolver = resolver or RefResolver()
    result = PinResult()
    for path in workflow_files(repo_root):
        rel_path = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8")
        pinned = pin_text(text, rel_path, resolver, result)
        if pinned != text:
            result.updated_files[rel_path] = pinned
    return result
