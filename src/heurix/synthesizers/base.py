"""
Base Synthesizer Interface for Heurix.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict
from heurix.core.context import ProjectContext


class BaseSynthesizer(ABC):
    """
    Abstract synthesizer that generates YAML files from a ProjectContext.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the synthesizer."""
        pass

    @abstractmethod
    def synthesize(self, context: ProjectContext) -> Dict[str, str]:
        """
        Generate target YAML files.
        Returns a dictionary of { relative_file_path: yaml_content }.
        """
        pass
