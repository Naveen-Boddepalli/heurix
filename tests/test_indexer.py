"""
Tests for RepoIndexer.
"""

from __future__ import annotations

import os
from pathlib import Path
from heurix.core.indexer import RepoIndexer


def test_indexer_ignores_and_caches(tmp_path: Path):
    # Setup simulated directory
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "some_lib.py").write_text("dummy", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "root"}', encoding="utf-8")

    indexer = RepoIndexer(tmp_path)

    assert indexer.has_file("src/main.py")
    assert indexer.has_file("package.json")
    assert not indexer.has_file(".venv/some_lib.py")
    assert not indexer.has_file("node_modules/package.json")

    content = indexer.read_text("src/main.py")
    assert content == "print('hello')"

    # Check cache
    assert "src/main.py" in indexer._content_cache
