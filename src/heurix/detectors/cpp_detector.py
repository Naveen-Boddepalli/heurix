"""
C / C++ Ecosystem Detector.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence
from heurix.core.context import LanguageContext, MonorepoPackage, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.core.monorepo import NON_PACKAGE_DIRS, discover_monorepo_topology
from heurix.detectors.base import BaseDetector

_STRICT_ROOT_INDICATORS = ("CMakeLists.txt", "conanfile.txt", "conanfile.py", "vcpkg.json")
_CPP_SOURCE_PATTERNS = ("*.cpp", "*.cc", "*.cxx", "*.hpp", "*.hxx", "*.c", "*.h")


def _join(base_dir: str, fname: str) -> str:
    return fname if base_dir == "." else f"{base_dir}/{fname}"


def _has_root_cpp(indexer: RepoIndexer, cpp_sub_dirs: Sequence[str]) -> bool:
    if any(indexer.has_file(f) for f in _STRICT_ROOT_INDICATORS):
        return True

    if not cpp_sub_dirs:
        return any(bool(indexer.find_files(pat)) for pat in _CPP_SOURCE_PATTERNS)

    for pat in _CPP_SOURCE_PATTERNS:
        for src_file in indexer.find_files(pat):
            if any(src_file == d or src_file.startswith(f"{d}/") for d in cpp_sub_dirs):
                continue
            top = src_file.split("/", 1)[0].lower() if "/" in src_file else ""
            if top and top in NON_PACKAGE_DIRS:
                continue
            return True
    return False


class CppDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "C++"

    def detect(self, indexer: RepoIndexer) -> bool:
        if any(indexer.has_file(f) for f in _STRICT_ROOT_INDICATORS):
            return True
        if discover_monorepo_topology(indexer).packages_by_lang.get("cpp"):
            return True
        return any(bool(indexer.find_files(pat)) for pat in ("*.cpp", "*.cc", "*.hpp", "*.c", "*.h"))

    def _analyze_cpp_dir(
        self,
        indexer: RepoIndexer,
        context: ProjectContext,
        base_dir: str,
        *,
        add_language_ctx: bool = True,
        add_monorepo_pkg: bool = False,
        is_workspace_root: Optional[bool] = None,
    ) -> LanguageContext:
        scope_label = f" in {base_dir}" if base_dir != "." else ""
        package_manager = "cmake"
        install_cmd = ""
        build_cmd = "cmake -B build -S . && cmake --build build"
        test_cmd = "ctest --test-dir build --output-on-failure"
        runtime_version = "latest"
        version_source = "system"

        cmake_path = _join(base_dir, "CMakeLists.txt")
        if indexer.has_file(_join(base_dir, "conanfile.txt")) or indexer.has_file(_join(base_dir, "conanfile.py")):
            package_manager = "conan"
            install_cmd = "conan install . --output-folder=build --build=missing"
            context.add_explain(f"Detected Package Manager{scope_label}: Conan")
        elif indexer.has_file(_join(base_dir, "vcpkg.json")):
            package_manager = "vcpkg"
            install_cmd = "vcpkg install"
            context.add_explain(f"Detected Package Manager{scope_label}: vcpkg")
        elif indexer.has_file(cmake_path):
            package_manager = "cmake"
            install_cmd = "cmake -B build -S . -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"
            build_cmd = "cmake -B build -S . -DCMAKE_EXPORT_COMPILE_COMMANDS=ON && cmake --build build"
            context.add_explain(f"Detected Build Tool{scope_label}: CMake (via {cmake_path})")
        elif indexer.has_file(_join(base_dir, "Makefile")):
            package_manager = "make"
            install_cmd = ""
            build_cmd = "make"
            test_cmd = "make test"
            context.add_explain(f"Detected Build Tool{scope_label}: Make (via {_join(base_dir, 'Makefile')})")

        if indexer.has_file(cmake_path):
            content = indexer.read_text(cmake_path) or ""
            std_match = re.search(r"set\s*\(\s*CMAKE_CXX_STANDARD\s+(\d+)\s*\)", content, re.IGNORECASE)
            if std_match:
                runtime_version = f"c++{std_match.group(1)}"
                version_source = "CMakeLists.txt"

        lint_cmd: Optional[str] = None
        if indexer.has_file(_join(base_dir, ".clang-tidy")):
            lint_cmd = "clang-tidy -p build"
            context.add_explain(f"Detected Linter{scope_label}: clang-tidy (via {_join(base_dir, '.clang-tidy')})")

        final_install = install_cmd or "echo 'No package manager'"
        lang_ctx = LanguageContext(
            language="cpp",
            runtime_version=runtime_version,
            version_source=version_source,
            package_manager=package_manager,
            install_cmd=final_install,
            build_cmd=build_cmd,
            test_cmd=test_cmd,
            lint_cmd=lint_cmd,
            working_dir=base_dir,
            confidence=0.90,
            is_workspace_root=is_workspace_root,
        )

        if add_language_ctx:
            context.languages.append(lang_ctx)

        if add_monorepo_pkg:
            context.monorepo_packages.append(
                MonorepoPackage(
                    name=base_dir,
                    path=base_dir,
                    language="cpp",
                    package_manager=package_manager,
                    runtime_version=runtime_version,
                    version_source=version_source,
                    install_cmd=final_install,
                    build_cmd=build_cmd,
                    test_cmd=test_cmd,
                    lint_cmd=lint_cmd,
                )
            )

        return lang_ctx

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing C / C++ ecosystem...")

        topo = discover_monorepo_topology(indexer)
        cpp_sub_dirs = topo.packages_by_lang.get("cpp", [])
        if topo.is_monorepo:
            context.is_monorepo = True

        if _has_root_cpp(indexer, cpp_sub_dirs):
            self._analyze_cpp_dir(
                indexer,
                context,
                ".",
                add_language_ctx=True,
                add_monorepo_pkg=False,
                is_workspace_root=False,
            )
            for sub_dir in cpp_sub_dirs:
                self._analyze_cpp_dir(
                    indexer,
                    context,
                    sub_dir,
                    add_language_ctx=False,
                    add_monorepo_pkg=True,
                )
        else:
            for idx, sub_dir in enumerate(cpp_sub_dirs):
                self._analyze_cpp_dir(
                    indexer,
                    context,
                    sub_dir,
                    add_language_ctx=(idx == 0),
                    add_monorepo_pkg=True,
                    is_workspace_root=None,
                )

