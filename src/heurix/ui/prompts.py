"""
Interactive Ambiguity Resolution and Hook Prompts with Non-TTY / EOFError Safety.
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import questionary
from rich.console import Console

from heurix.core.context import DeploymentTarget, ProjectContext, ServiceRequirement

console = Console()


def is_interactive_tty() -> bool:
    """Return True only when stdin is attached to an interactive terminal."""
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


def prompt_conflict_resolution(file_path: str, non_interactive: bool = False) -> str:
    """
    Prompt user when an existing file would be modified.
    Returns: 'apply', 'diff', 'skip', or 'backup'
    """
    if non_interactive or not is_interactive_tty():
        return "apply"

    try:
        choice = questionary.select(
            f"File '{file_path}' already exists. What would you like to do?",
            choices=[
                questionary.Choice(
                    title="[A] Apply changes (non-destructive smart merge)", value="apply"
                ),
                questionary.Choice(title="[D] View diff preview", value="diff"),
                questionary.Choice(title="[B] Backup & overwrite", value="backup"),
                questionary.Choice(title="[S] Skip file", value="skip"),
            ],
        ).ask()
        return choice or "apply"
    except EOFError:
        return "apply"


def prompt_e2e_split(
    unit_runners: Sequence[str],
    e2e_runners: Sequence[str],
    *,
    non_interactive: bool = False,
) -> bool:
    """
    Prompt whether to isolate detected E2E tests into a parallel 'test-e2e' job.
    Defaults to True in headless/non-TTY modes.
    """
    if non_interactive or not is_interactive_tty():
        return True

    try:
        answer = questionary.confirm(
            f"Detected both unit ({', '.join(unit_runners)}) and E2E ({', '.join(e2e_runners)}) "
            "test runners. Isolate E2E tests into a parallel 'test-e2e' CI job?",
            default=True,
        ).ask()
        return True if answer is None else bool(answer)
    except EOFError:
        return True


def prompt_deployment_targets(
    targets: Sequence[DeploymentTarget],
    *,
    non_interactive: bool = False,
) -> List[DeploymentTarget]:
    """
    Prompt user to confirm/select deployment targets when 2+ platforms are detected.
    Distinguishes abort (None -> keep all) from explicit empty selection ([] -> []).
    """
    if non_interactive or not is_interactive_tty() or len(targets) < 2:
        return list(targets)

    seen_platforms: set[str] = set()
    choices = []
    for target in targets:
        platform_key = target.platform.lower()
        if platform_key in seen_platforms:
            continue
        seen_platforms.add(platform_key)
        choices.append(
            questionary.Choice(
                title=f"{target.platform} ({target.config_file}, project: {target.project_id or 'auto'})",
                value=target.platform,
                checked=True,
            )
        )

    try:
        selected = questionary.checkbox(
            "Multiple cloud deployment targets detected. Select targets to synthesize:",
            choices=choices,
        ).ask()
        if selected is None:
            return list(targets)
        selected_set = {str(item).lower() for item in selected}
        return [t for t in targets if t.platform.lower() in selected_set]
    except EOFError:
        return list(targets)


def prompt_backing_services(
    services: Sequence[ServiceRequirement],
    *,
    non_interactive: bool = False,
) -> List[ServiceRequirement]:
    """
    Prompt user to confirm or exclude detected backing services when 2+ are present.
    Deduplicates choice values by service name cleanly.
    """
    if non_interactive or not is_interactive_tty() or len(services) < 2:
        return list(services)

    grouped: Dict[str, Tuple[str, List[int]]] = {}
    for svc in services:
        key = svc.name.lower()
        if key not in grouped:
            grouped[key] = (svc.name, sorted(set(svc.ports)))
        else:
            display_name, existing_ports = grouped[key]
            grouped[key] = (display_name, sorted(set(existing_ports) | set(svc.ports)))

    choices = []
    for display_name, ports in grouped.values():
        ports_summary = ", ".join(str(p) for p in ports) if ports else "default"
        choices.append(
            questionary.Choice(
                title=f"{display_name} (ports: {ports_summary})",
                value=display_name,
                checked=True,
            )
        )

    try:
        selected = questionary.checkbox(
            "Multiple backing services detected. Select services to include:",
            choices=choices,
        ).ask()
        if selected is None:
            return list(services)
        selected_set = {str(item).lower() for item in selected}
        return [svc for svc in services if svc.name.lower() in selected_set]
    except EOFError:
        return list(services)


def prompt_k8s_generation(
    *,
    default: bool = True,
    non_interactive: bool = False,
) -> bool:
    """Prompt user whether to synthesize optional Kubernetes manifests when policy is unset."""
    if non_interactive or not is_interactive_tty():
        return default

    try:
        answer = questionary.confirm(
            "Container configuration detected without explicit Kubernetes policy. "
            "Generate Kubernetes manifests (k8s/)?",
            default=default,
        ).ask()
        return default if answer is None else bool(answer)
    except EOFError:
        return default


def prompt_install_hooks(*, non_interactive: bool = False) -> bool:
    """
    Prompt user whether to install the Git pre-commit hook during interactive 'hx init'.
    Always returns False in non-interactive or non-TTY modes so headless runs never mutate .git/hooks/.
    """
    if non_interactive or not is_interactive_tty():
        return False

    try:
        answer = questionary.confirm(
            "Git repository detected. Install an idempotent pre-commit hook running 'hx check'?",
            default=True,
        ).ask()
        return False if answer is None else bool(answer)
    except EOFError:
        return False


def collect_e2e_signals(context: ProjectContext) -> Tuple[List[str], List[str]]:
    """Collect deduplicated unit and E2E test runner names across languages and monorepo packages."""
    unit_runners: List[str] = []
    e2e_runners: List[str] = []

    for source in (*context.languages, *context.monorepo_packages):
        if source.unit_test_runner and source.unit_test_runner not in unit_runners:
            unit_runners.append(source.unit_test_runner)
        if source.e2e_test_runner and source.e2e_test_runner not in e2e_runners:
            e2e_runners.append(source.e2e_test_runner)

    return unit_runners, e2e_runners


def resolve_context_ambiguities(
    context: ProjectContext,
    *,
    include_k8s: bool,
    k8s_policy_explicit: bool,
    services_policy_explicit: bool,
    non_interactive: bool = False,
    e2e_prompt: Optional[Callable[..., bool]] = None,
    targets_prompt: Optional[Callable[..., List[DeploymentTarget]]] = None,
    services_prompt: Optional[Callable[..., List[ServiceRequirement]]] = None,
    k8s_prompt: Optional[Callable[..., bool]] = None,
) -> Tuple[ProjectContext, bool]:
    """
    Resolve codebase ambiguities interactively (or deterministically in non-interactive/non-TTY modes)
    on a deep-copied ProjectContext without stripping SEC-03 deployment_secrets protections.
    """
    resolved = context.model_copy(deep=True)

    e2e_fn = e2e_prompt or prompt_e2e_split
    targets_fn = targets_prompt or prompt_deployment_targets
    services_fn = services_prompt or prompt_backing_services
    k8s_fn = k8s_prompt or prompt_k8s_generation

    unit_runners, e2e_runners = collect_e2e_signals(resolved)
    if unit_runners and e2e_runners:
        resolved.split_e2e_jobs = bool(
            e2e_fn(unit_runners, e2e_runners, non_interactive=non_interactive)
        )

    if len(resolved.deployment_targets) >= 2:
        # Preserve resolved.deployment_secrets untouched so SEC-03 isolation holds even for deselected targets.
        resolved.deployment_targets = list(
            targets_fn(resolved.deployment_targets, non_interactive=non_interactive)
        )

    if not services_policy_explicit and len(resolved.services) >= 2:
        resolved.services = list(
            services_fn(resolved.services, non_interactive=non_interactive)
        )

    resolved_include_k8s = include_k8s
    if include_k8s and not k8s_policy_explicit and resolved.containers:
        resolved_include_k8s = bool(
            k8s_fn(default=include_k8s, non_interactive=non_interactive)
        )

    return resolved, resolved_include_k8s
