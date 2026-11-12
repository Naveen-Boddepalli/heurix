"""
Tests for Questionary ambiguity prompts, non-TTY/EOFError safety, and Git pre-commit hooks.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

import heurix.ui.prompts as prompts_mod
from heurix.cli import resolve_safe_path
from heurix.core.context import (
    ContainerContext,
    DeploymentTarget,
    LanguageContext,
    MonorepoPackage,
    ProjectContext,
    ServiceRequirement,
)
from heurix.core.hooks import (
    HOOK_END_MARKER,
    HOOK_START_MARKER,
    MANAGED_PRE_COMMIT_BLOCK,
    HookInstallResult,
    install_pre_commit_hook,
    upsert_managed_hook_block,
)


class _FakeAsk:
    def __init__(self, result: Any = None, *, exc: type[BaseException] | None = None):
        self._result = result
        self._exc = exc

    def ask(self) -> Any:
        if self._exc is not None:
            raise self._exc("EOF when reading a line")
        return self._result


def _make_sample_targets() -> list[DeploymentTarget]:
    return [
        DeploymentTarget(
            platform="vercel",
            config_file="vercel.json",
            project_id="my-vercel",
            features=["hosting"],
            required_secrets=["VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID"],
        ),
        DeploymentTarget(
            platform="firebase",
            config_file="firebase.json",
            project_id="my-firebase",
            features=["hosting"],
            required_secrets=["FIREBASE_SERVICE_ACCOUNT"],
        ),
    ]


def _make_sample_services() -> list[ServiceRequirement]:
    return [
        ServiceRequirement(name="postgres", image="postgres:16-alpine", ports=[5432]),
        ServiceRequirement(name="redis", image="redis:7-alpine", ports=[6379]),
    ]


def test_prompts_non_tty_and_eoferror_fallbacks(monkeypatch):
    # 1. is_interactive_tty edge cases
    class _FakeStdin:
        def __init__(self, tty_value=False, raises=False):
            self._tty_value = tty_value
            self._raises = raises

        def isatty(self):
            if self._raises:
                raise OSError("bad fd")
            return self._tty_value

    monkeypatch.setattr(prompts_mod.sys, "stdin", None)
    assert prompts_mod.is_interactive_tty() is False

    monkeypatch.setattr(prompts_mod.sys, "stdin", _FakeStdin(raises=True))
    assert prompts_mod.is_interactive_tty() is False

    monkeypatch.setattr(prompts_mod.sys, "stdin", _FakeStdin(tty_value=False))
    assert prompts_mod.is_interactive_tty() is False

    monkeypatch.setattr(prompts_mod.sys, "stdin", _FakeStdin(tty_value=True))
    assert prompts_mod.is_interactive_tty() is True

    # 2. Non-TTY mode must NEVER invoke questionary and must return safe deterministic defaults
    def _forbid_questionary(*args, **kwargs):
        raise AssertionError("questionary must not be called in non-TTY or non-interactive mode")

    monkeypatch.setattr(prompts_mod.questionary, "select", _forbid_questionary)
    monkeypatch.setattr(prompts_mod.questionary, "confirm", _forbid_questionary)
    monkeypatch.setattr(prompts_mod.questionary, "checkbox", _forbid_questionary)
    monkeypatch.setattr(prompts_mod, "is_interactive_tty", lambda: False)

    targets = _make_sample_targets()
    services = _make_sample_services()

    assert prompts_mod.prompt_conflict_resolution(".github/workflows/ci.yml") == "apply"
    assert prompts_mod.prompt_e2e_split(["vitest"], ["playwright"]) is True
    assert prompts_mod.prompt_deployment_targets(targets) == targets
    assert prompts_mod.prompt_backing_services(services) == services
    assert prompts_mod.prompt_k8s_generation(default=True) is True
    assert prompts_mod.prompt_k8s_generation(default=False) is False
    assert prompts_mod.prompt_install_hooks() is False

    # Even with TTY=True, non_interactive=True bypasses questionary safely
    monkeypatch.setattr(prompts_mod, "is_interactive_tty", lambda: True)
    assert prompts_mod.prompt_conflict_resolution("ci.yml", non_interactive=True) == "apply"
    assert prompts_mod.prompt_e2e_split(["pytest"], ["playwright"], non_interactive=True) is True
    assert prompts_mod.prompt_deployment_targets(targets, non_interactive=True) == targets
    assert prompts_mod.prompt_backing_services(services, non_interactive=True) == services
    assert prompts_mod.prompt_k8s_generation(default=False, non_interactive=True) is False
    assert prompts_mod.prompt_install_hooks(non_interactive=True) is False

    # Single target / single service skips prompting even in interactive TTY
    assert prompts_mod.prompt_deployment_targets([targets[0]]) == [targets[0]]
    assert prompts_mod.prompt_backing_services([services[0]]) == [services[0]]

    # 3. EOFError resilience when is_interactive_tty is True
    monkeypatch.setattr(
        prompts_mod.questionary, "select", lambda *a, **kw: _FakeAsk(exc=EOFError)
    )
    monkeypatch.setattr(
        prompts_mod.questionary, "confirm", lambda *a, **kw: _FakeAsk(exc=EOFError)
    )
    monkeypatch.setattr(
        prompts_mod.questionary, "checkbox", lambda *a, **kw: _FakeAsk(exc=EOFError)
    )

    assert prompts_mod.prompt_conflict_resolution("ci.yml") == "apply"
    assert prompts_mod.prompt_e2e_split(["vitest"], ["playwright"]) is True
    assert prompts_mod.prompt_deployment_targets(targets) == targets
    assert prompts_mod.prompt_backing_services(services) == services
    assert prompts_mod.prompt_k8s_generation(default=False) is False
    assert prompts_mod.prompt_install_hooks() is False

    # 4. Checkbox None (abort) vs explicit [] (deselect all) and choice deduplication
    captured_choices: list[Any] = []

    def _mock_checkbox_none(msg, choices, **kwargs):
        captured_choices.append(choices)
        return _FakeAsk(None)

    monkeypatch.setattr(prompts_mod.questionary, "checkbox", _mock_checkbox_none)
    assert prompts_mod.prompt_deployment_targets(targets) == targets
    dup_services = [
        ServiceRequirement(name="postgres", image="postgres:16-alpine", ports=[5432], package_path="api"),
        ServiceRequirement(name="postgres", image="postgres:16-alpine", ports=[5432], package_path="worker"),
        ServiceRequirement(name="redis", image="redis:7-alpine", ports=[6379]),
    ]
    assert prompts_mod.prompt_backing_services(dup_services) == dup_services
    # Duplicate 'postgres' values must be deduplicated cleanly in choices
    assert [c.value for c in captured_choices[-1]] == ["postgres", "redis"]

    monkeypatch.setattr(
        prompts_mod.questionary, "checkbox", lambda *a, **kw: _FakeAsk([])
    )
    assert prompts_mod.prompt_deployment_targets(targets) == []
    assert prompts_mod.prompt_backing_services(services) == []

    # 5. Interactive Questionary selections + resolve_context_ambiguities + SEC-03 guard
    confirm_answers = iter([False, False, True])  # e2e_split=False, k8s=False, install_hooks=True

    def _mock_confirm(msg, **kwargs):
        return _FakeAsk(next(confirm_answers))

    def _mock_checkbox(msg, choices, **kwargs):
        values = [c.value for c in choices]
        if "vercel" in values:
            return _FakeAsk(["vercel"])  # deselect firebase
        if "postgres" in values:
            return _FakeAsk(["postgres"])  # exclude redis
        return _FakeAsk(values)

    monkeypatch.setattr(prompts_mod.questionary, "confirm", _mock_confirm)
    monkeypatch.setattr(prompts_mod.questionary, "checkbox", _mock_checkbox)

    ctx = ProjectContext(
        repo_name="e2e-cloud-app",
        repo_root="/tmp/e2e-cloud-app",
        languages=[
            LanguageContext(
                language="node",
                runtime_version="20.x",
                version_source=".nvmrc",
                package_manager="npm",
                install_cmd="npm ci",
                test_cmd="npm test",
                unit_test_runner="vitest",
                e2e_test_runner="playwright",
                e2e_cmd="npm run test:e2e",
            )
        ],
        monorepo_packages=[
            MonorepoPackage(
                name="apps/web",
                path="apps/web",
                language="node",
                package_manager="pnpm",
                unit_test_runner="vitest",
                e2e_test_runner="playwright",
                e2e_cmd="pnpm run test:e2e",
            )
        ],
        services=dup_services,
        containers=[ContainerContext(dockerfile_path="Dockerfile", exposed_ports=[8000])],
        deployment_targets=targets,
        test_secrets=["DATABASE_URL"],
        deployment_secrets=["VERCEL_TOKEN", "FIREBASE_SERVICE_ACCOUNT"],
    )

    unit_runners, e2e_runners = prompts_mod.collect_e2e_signals(ctx)
    assert unit_runners == ["vitest"]
    assert e2e_runners == ["playwright"]

    resolved_ctx, resolved_k8s = prompts_mod.resolve_context_ambiguities(
        ctx,
        include_k8s=True,
        k8s_policy_explicit=False,
        services_policy_explicit=False,
        non_interactive=False,
    )

    # Original context remains untouched
    assert ctx.split_e2e_jobs is None
    assert len(ctx.deployment_targets) == 2
    assert len(ctx.services) == 3

    # Resolved copy applies selections while keeping SEC-03 deployment_secrets intact
    assert resolved_ctx.split_e2e_jobs is False
    assert [t.platform for t in resolved_ctx.deployment_targets] == ["vercel"]
    assert "FIREBASE_SERVICE_ACCOUNT" in resolved_ctx.deployment_secrets
    assert "VERCEL_TOKEN" in resolved_ctx.deployment_secrets
    assert "FIREBASE_SERVICE_ACCOUNT" not in resolved_ctx.test_secrets
    assert [s.name for s in resolved_ctx.services] == ["postgres", "postgres"]
    assert resolved_k8s is False

    assert prompts_mod.prompt_install_hooks() is True

    # Policy explicit flags suppress service and k8s prompts
    resolved_explicit, resolved_k8s_explicit = prompts_mod.resolve_context_ambiguities(
        ctx,
        include_k8s=True,
        k8s_policy_explicit=True,
        services_policy_explicit=True,
        non_interactive=False,
        e2e_prompt=lambda u, e, non_interactive=False: True,
        targets_prompt=lambda t, non_interactive=False: list(t),
        services_prompt=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("services prompt skipped")),
        k8s_prompt=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("k8s prompt skipped")),
    )
    assert resolved_explicit.split_e2e_jobs is True
    assert len(resolved_explicit.services) == 3
    assert resolved_k8s_explicit is True


def test_hooks_idempotent_preserve_chmod_and_security(tmp_path: Path, monkeypatch):
    # 0. Managed block safety contract (no 'exec', exact marker fences)
    assert MANAGED_PRE_COMMIT_BLOCK.startswith(HOOK_START_MARKER)
    assert MANAGED_PRE_COMMIT_BLOCK.rstrip().endswith(HOOK_END_MARKER)
    assert "exec " not in MANAGED_PRE_COMMIT_BLOCK
    assert "\nexec\n" not in MANAGED_PRE_COMMIT_BLOCK

    # 1. upsert_managed_hook_block unit behavior (empty, append, replace, CRLF, idempotent)
    fresh_text = upsert_managed_hook_block("")
    assert fresh_text.startswith("#!/usr/bin/env sh\n\n# >>> heurix:pre-commit\n")
    assert fresh_text.endswith("# <<< heurix:pre-commit\n")
    assert upsert_managed_hook_block(fresh_text) == fresh_text

    custom_crlf = "#!/bin/sh\r\necho 'custom-pre'\r\n"
    appended = upsert_managed_hook_block(custom_crlf)
    assert "\r" not in appended
    assert appended.startswith("#!/bin/sh\necho 'custom-pre'\n\n# >>> heurix:pre-commit\n")
    assert upsert_managed_hook_block(appended) == appended

    stale_with_surrounding = (
        "#!/usr/bin/env sh\n"
        "echo 'before-hook'\n\n"
        f"{HOOK_START_MARKER}\n"
        "echo 'stale heurix hook'\n"
        f"{HOOK_END_MARKER}\n\n"
        "echo 'after-hook'\n"
    )
    replaced = upsert_managed_hook_block(stale_with_surrounding)
    assert "stale heurix hook" not in replaced
    assert "echo 'before-hook'" in replaced
    assert "echo 'after-hook'" in replaced
    assert replaced.count(HOOK_START_MARKER) == 1
    assert replaced.count(HOOK_END_MARKER) == 1
    assert upsert_managed_hook_block(replaced) == replaced

    # 2. Missing .git directory skips cleanly without creating files
    no_git_repo = tmp_path / "no_git"
    no_git_repo.mkdir()
    skip_res = install_pre_commit_hook(no_git_repo, resolve_safe_path)
    assert isinstance(skip_res, HookInstallResult)
    assert skip_res.installed is False
    assert skip_res.hook_path is None
    assert skip_res.status == "skipped_no_git"
    assert not (no_git_repo / ".git").exists()

    # Regular .git file (e.g., worktree pointer) also returns skipped_no_git safely
    file_git_repo = tmp_path / "file_git"
    file_git_repo.mkdir()
    (file_git_repo / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    file_skip_res = install_pre_commit_hook(file_git_repo, resolve_safe_path)
    assert file_skip_res.installed is False
    assert file_skip_res.status == "skipped_no_git"

    # 3. Fresh .git/ creation sets 0o755 and is byte-identical on repeat runs
    fresh_repo = tmp_path / "fresh_repo"
    (fresh_repo / ".git").mkdir(parents=True)
    create_res = install_pre_commit_hook(fresh_repo, resolve_safe_path)
    hook_file = fresh_repo / ".git" / "hooks" / "pre-commit"
    assert create_res.installed is True
    assert create_res.status == "created"
    assert create_res.hook_path == hook_file.resolve()
    assert hook_file.is_file()
    assert stat.S_IMODE(hook_file.stat().st_mode) == 0o755

    first_bytes = hook_file.read_bytes()
    repeat_res = install_pre_commit_hook(fresh_repo, resolve_safe_path)
    assert repeat_res.installed is True
    assert repeat_res.status == "unchanged"
    assert hook_file.read_bytes() == first_bytes

    # 4. Existing custom pre-commit script with lines before AND after managed block
    custom_repo = tmp_path / "custom_repo"
    (custom_repo / ".git" / "hooks").mkdir(parents=True)
    custom_hook = custom_repo / ".git" / "hooks" / "pre-commit"
    custom_hook.write_text(
        "#!/usr/bin/env sh\n"
        "echo 'before' >> \"$TRACE_FILE\"\n\n"
        f"{HOOK_START_MARKER}\n"
        "echo 'old-heurix'\n"
        f"{HOOK_END_MARKER}\n\n"
        "echo 'after' >> \"$TRACE_FILE\"\n",
        encoding="utf-8",
    )
    custom_hook.chmod(0o644)

    update_res = install_pre_commit_hook(custom_repo, resolve_safe_path)
    assert update_res.installed is True
    assert update_res.status == "updated"
    assert stat.S_IMODE(custom_hook.stat().st_mode) == 0o755
    updated_content = custom_hook.read_text(encoding="utf-8")
    assert "echo 'before' >> \"$TRACE_FILE\"" in updated_content
    assert "echo 'after' >> \"$TRACE_FILE\"" in updated_content
    assert "old-heurix" not in updated_content

    # Repeat run stays unchanged and byte-identical
    repeat_custom_res = install_pre_commit_hook(custom_repo, resolve_safe_path)
    assert repeat_custom_res.status == "unchanged"
    assert custom_hook.read_text(encoding="utf-8") == updated_content

    # Execute the installed hook via /bin/sh to verify post-block lines run on pass and abort on fail
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    fake_hx = fake_bin / "hx"
    fake_hx.write_text(
        "#!/usr/bin/env sh\n"
        "echo \"hx:$*\" >> \"$TRACE_FILE\"\n"
        "exit \"${FAKE_HX_EXIT:-0}\"\n",
        encoding="utf-8",
    )
    fake_hx.chmod(0o755)

    trace_pass = tmp_path / "trace_pass.log"
    env_pass = {
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path / "empty_home"),
        "TRACE_FILE": str(trace_pass),
        "FAKE_HX_EXIT": "0",
    }
    proc_pass = subprocess.run(
        ["/bin/sh", str(custom_hook)],
        cwd=custom_repo,
        env=env_pass,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_pass.returncode == 0
    assert trace_pass.read_text(encoding="utf-8").splitlines() == [
        "before",
        "hx:check --path .",
        "after",
    ]

    trace_fail = tmp_path / "trace_fail.log"
    env_fail = {**env_pass, "TRACE_FILE": str(trace_fail), "FAKE_HX_EXIT": "2"}
    proc_fail = subprocess.run(
        ["/bin/sh", str(custom_hook)],
        cwd=custom_repo,
        env=env_fail,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_fail.returncode == 2
    assert trace_fail.read_text(encoding="utf-8").splitlines() == [
        "before",
        "hx:check --path .",
    ]

    # .venv/bin/hx fallback when hx is not on PATH
    venv_bin = custom_repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_hx = venv_bin / "hx"
    venv_hx.write_text(
        "#!/usr/bin/env sh\n"
        "echo \"venv-hx:$*\" >> \"$TRACE_FILE\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    venv_hx.chmod(0o755)
    trace_venv = tmp_path / "trace_venv.log"
    env_venv = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "empty_home"),
        "TRACE_FILE": str(trace_venv),
    }
    proc_venv = subprocess.run(
        ["/bin/sh", str(custom_hook)],
        cwd=custom_repo,
        env=env_venv,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_venv.returncode == 0
    assert trace_venv.read_text(encoding="utf-8").splitlines() == [
        "before",
        "venv-hx:check --path .",
        "after",
    ]

    # 5. SEC-01 symlink traversal escapes blocked before mkdir/read/write
    outside_dir = tmp_path / "outside_target"
    outside_dir.mkdir()

    # 5a. Symlinked .git pointing outside repo_path
    esc_git_repo = tmp_path / "esc_git_repo"
    esc_git_repo.mkdir()
    (esc_git_repo / ".git").symlink_to(outside_dir)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        install_pre_commit_hook(esc_git_repo, resolve_safe_path)
    assert not (outside_dir / "hooks").exists()

    # Also test default internal SEC-01 boundary check when path_resolver is omitted
    with pytest.raises(ValueError, match="Path traversal security violation"):
        install_pre_commit_hook(esc_git_repo)

    # 5b. Symlinked .git/hooks pointing outside repo_path
    esc_hooks_repo = tmp_path / "esc_hooks_repo"
    (esc_hooks_repo / ".git").mkdir(parents=True)
    (esc_hooks_repo / ".git" / "hooks").symlink_to(outside_dir)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        install_pre_commit_hook(esc_hooks_repo, resolve_safe_path)
    assert not (outside_dir / "pre-commit").exists()

    # 5c. Symlinked .git/hooks/pre-commit pointing outside repo_path
    esc_file_repo = tmp_path / "esc_file_repo"
    (esc_file_repo / ".git" / "hooks").mkdir(parents=True)
    outside_hook = outside_dir / "pwned_pre_commit"
    (esc_file_repo / ".git" / "hooks" / "pre-commit").symlink_to(outside_hook)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        install_pre_commit_hook(esc_file_repo, resolve_safe_path)
    assert not outside_hook.exists()

    # 6. Graceful OSError / PermissionError handling without unhandled tracebacks
    ro_repo = tmp_path / "ro_repo"
    ro_hooks = ro_repo / ".git" / "hooks"
    ro_hooks.mkdir(parents=True)
    if os.geteuid() != 0:
        ro_hooks.chmod(0o555)
        try:
            ro_res = install_pre_commit_hook(ro_repo, resolve_safe_path)
            assert ro_res.installed is False
            assert ro_res.status == "error"
            assert ro_res.hook_path == (ro_hooks / "pre-commit").resolve()
            assert ro_res.message
        finally:
            ro_hooks.chmod(0o755)

    # Deterministic PermissionError check independent of UID / filesystem ACLs
    def _deny_write(*args, **kwargs):
        raise PermissionError("Permission denied: simulated read-only .git/hooks")

    monkeypatch.setattr(Path, "write_text", _deny_write)
    perm_res = install_pre_commit_hook(ro_repo, resolve_safe_path)
    assert perm_res.installed is False
    assert perm_res.status == "error"
    assert perm_res.hook_path == (ro_hooks / "pre-commit").resolve()
    assert "Permission denied" in perm_res.message

