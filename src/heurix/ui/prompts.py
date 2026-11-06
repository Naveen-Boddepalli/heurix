"""
Interactive Ambiguity Resolution Prompts.
"""

from __future__ import annotations

import questionary
from rich.console import Console

console = Console()


def prompt_conflict_resolution(file_path: str, non_interactive: bool = False) -> str:
    """
    Prompt user when an existing file would be modified.
    Returns: 'apply', 'diff', 'skip', or 'backup'
    """
    if non_interactive:
        return "apply"

    choice = questionary.select(
        f"File '{file_path}' already exists. What would you like to do?",
        choices=[
            questionary.Choice(title="[A] Apply changes (non-destructive smart merge)", value="apply"),
            questionary.Choice(title="[D] View diff preview", value="diff"),
            questionary.Choice(title="[B] Backup & overwrite", value="backup"),
            questionary.Choice(title="[S] Skip file", value="skip"),
        ],
    ).ask()

    return choice or "apply"


def prompt_e2e_parallel(non_interactive: bool = False) -> bool:
    """
    Ask if E2E tests should run in a separate parallel job.
    """
    if non_interactive:
        return True

    return questionary.confirm(
        "Detected Playwright / E2E test runner alongside unit tests. Run E2E in a separate parallel job?",
        default=True,
    ).ask() or False
