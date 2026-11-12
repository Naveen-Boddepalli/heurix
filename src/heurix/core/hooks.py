"""
Safe, idempotent Git pre-commit hook management with SEC-01 containment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

HOOK_START_MARKER = "# >>> heurix:pre-commit"
HOOK_END_MARKER = "# <<< heurix:pre-commit"

MANAGED_PRE_COMMIT_BLOCK = """# >>> heurix:pre-commit
if command -v hx >/dev/null 2>&1; then
  hx check --path . || exit $?
elif [ -x ".venv/bin/hx" ]; then
  .venv/bin/hx check --path . || exit $?
elif [ -x "${HOME}/.local/bin/hx" ]; then
  "${HOME}/.local/bin/hx" check --path . || exit $?
else
  echo "heurix (hx) not found on PATH; skipping pre-commit drift check." >&2
fi
# <<< heurix:pre-commit"""


@dataclass(frozen=True)
class HookInstallResult:
    """Outcome of installing or updating a repository's pre-commit hook."""

    installed: bool
    hook_path: Optional[Path]
    status: str
    message: str


def _default_resolve_safe_path(base_dir: Path, rel_path: str | Path) -> Path:
    """Resolve rel_path within base_dir and enforce SEC-01 boundary containment."""
    base_resolved = base_dir.resolve()
    target_resolved = (base_resolved / rel_path).resolve()
    if not target_resolved.is_relative_to(base_resolved):
        raise ValueError(
            f"Path traversal security violation: path '{rel_path}' resolves outside repository root '{base_dir}'"
        )
    return target_resolved


def upsert_managed_hook_block(
    existing: str,
    block: str = MANAGED_PRE_COMMIT_BLOCK,
) -> str:
    """
    Insert or update the managed Heurix pre-commit block idempotently while
    preserving any existing custom hook shebang and commands.
    """
    norm = existing.replace("\r\n", "\n")
    block_text = block.strip()
    if not norm.strip():
        return f"#!/usr/bin/env sh\n\n{block_text}\n"

    lines = norm.splitlines()
    start_idx = next(
        (i for i, line in enumerate(lines) if line.strip() == HOOK_START_MARKER),
        None,
    )
    end_idx = (
        next(
            (i for i in range(start_idx + 1, len(lines)) if lines[i].strip() == HOOK_END_MARKER),
            None,
        )
        if start_idx is not None
        else None
    )

    block_lines = block_text.splitlines()
    if start_idx is not None and end_idx is not None and start_idx < end_idx:
        updated = [*lines[:start_idx], *block_lines, *lines[end_idx + 1 :]]
        return "\n".join(updated).rstrip("\n") + "\n"

    return norm.rstrip("\n") + "\n\n" + "\n".join(block_lines) + "\n"


def install_pre_commit_hook(
    repo_path: Path,
    path_resolver: Optional[Callable[[Path, str | Path], Path]] = None,
) -> HookInstallResult:
    """
    Safely install or update `.git/hooks/pre-commit` inside `repo_path`.

    Enforces SEC-01 boundary checks on `.git`, `.git/hooks`, and
    `.git/hooks/pre-commit` before any directory creation or file I/O.
    """
    repo_root = Path(repo_path)
    resolver = path_resolver or _default_resolve_safe_path

    raw_git = repo_root / ".git"
    if not raw_git.exists() and not raw_git.is_symlink():
        return HookInstallResult(
            installed=False,
            hook_path=None,
            status="skipped_no_git",
            message="No .git directory found; skipping pre-commit hook installation.",
        )

    git_dir = resolver(repo_root, ".git")
    if not git_dir.is_dir():
        return HookInstallResult(
            installed=False,
            hook_path=None,
            status="skipped_no_git",
            message="No .git directory found; skipping pre-commit hook installation.",
        )

    hooks_dir = resolver(repo_root, ".git/hooks")
    hook_path = resolver(repo_root, ".git/hooks/pre-commit")

    try:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        existed = hook_path.exists()
        existing = hook_path.read_text(encoding="utf-8") if existed else ""
        updated = upsert_managed_hook_block(existing)

        if not existed:
            hook_path.write_text(updated, encoding="utf-8")
            os.chmod(hook_path, 0o755)
            return HookInstallResult(
                installed=True,
                hook_path=hook_path,
                status="created",
                message=f"Installed pre-commit hook at {hook_path}",
            )

        if updated != existing:
            hook_path.write_text(updated, encoding="utf-8")
            os.chmod(hook_path, 0o755)
            return HookInstallResult(
                installed=True,
                hook_path=hook_path,
                status="updated",
                message=f"Updated pre-commit hook at {hook_path}",
            )

        os.chmod(hook_path, 0o755)
        return HookInstallResult(
            installed=True,
            hook_path=hook_path,
            status="unchanged",
            message=f"Pre-commit hook already up to date at {hook_path}",
        )
    except OSError as exc:
        return HookInstallResult(
            installed=False,
            hook_path=hook_path,
            status="error",
            message=str(exc),
        )
