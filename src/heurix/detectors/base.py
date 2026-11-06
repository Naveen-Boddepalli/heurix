"""
Abstract Base Detector for Heurix.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from heurix.core.context import ProjectContext
from heurix.core.indexer import RepoIndexer


class BaseDetector(ABC):
    """
    Modular detector interface adhering to the detect() -> analyze() lifecycle.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the detector (e.g., 'Python', 'Node', 'Docker')."""
        pass

    @abstractmethod
    def detect(self, indexer: RepoIndexer) -> bool:
        """
        Fast check if this language/technology is present in the repository.
        """
        pass

    @abstractmethod
    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        """
        Deep analysis: extract runtime versions, package managers, test commands,
        dependencies, and record explain logs.
        """
        pass
