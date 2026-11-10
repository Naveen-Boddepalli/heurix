"""
C / C++ Ecosystem Detector.
"""

from __future__ import annotations

import re
from heurix.core.context import LanguageContext, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


class CppDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "C++"

    def detect(self, indexer: RepoIndexer) -> bool:
        strict_indicators = ["CMakeLists.txt", "conanfile.txt", "conanfile.py", "vcpkg.json"]
        has_cpp_sources = (
            bool(indexer.find_files("*.cpp"))
            or bool(indexer.find_files("*.cc"))
            or bool(indexer.find_files("*.hpp"))
            or bool(indexer.find_files("*.c"))
            or bool(indexer.find_files("*.h"))
        )
        return any(indexer.has_file(f) for f in strict_indicators) or has_cpp_sources

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing C / C++ ecosystem...")

        package_manager = "cmake"
        install_cmd = ""
        build_cmd = "cmake -B build -S . && cmake --build build"
        test_cmd = "ctest --test-dir build --output-on-failure"
        runtime_version = "latest"
        version_source = "system"

        if indexer.has_file("conanfile.txt") or indexer.has_file("conanfile.py"):
            package_manager = "conan"
            install_cmd = "conan install . --output-folder=build --build=missing"
            context.add_explain("Detected Package Manager: Conan")
        elif indexer.has_file("vcpkg.json"):
            package_manager = "vcpkg"
            install_cmd = "vcpkg install"
            context.add_explain("Detected Package Manager: vcpkg")
        elif indexer.has_file("CMakeLists.txt"):
            package_manager = "cmake"
            install_cmd = "cmake -B build -S . -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"
            build_cmd = "cmake -B build -S . -DCMAKE_EXPORT_COMPILE_COMMANDS=ON && cmake --build build"
            context.add_explain("Detected Build Tool: CMake (via CMakeLists.txt)")
            content = indexer.read_text("CMakeLists.txt") or ""
            std_match = re.search(r"set\s*\(\s*CMAKE_CXX_STANDARD\s+(\d+)\s*\)", content, re.IGNORECASE)
            if std_match:
                runtime_version = f"c++{std_match.group(1)}"
                version_source = "CMakeLists.txt"
        elif indexer.has_file("Makefile"):
            package_manager = "make"
            install_cmd = ""
            build_cmd = "make"
            test_cmd = "make test"
            context.add_explain("Detected Build Tool: Make (via Makefile)")

        lint_cmd = None
        if indexer.has_file(".clang-tidy"):
            lint_cmd = "clang-tidy -p build"
            context.add_explain("Detected Linter: clang-tidy (via .clang-tidy)")

        context.languages.append(
            LanguageContext(
                language="cpp",
                runtime_version=runtime_version,
                version_source=version_source,
                package_manager=package_manager,
                install_cmd=install_cmd or "echo 'No package manager'",
                build_cmd=build_cmd,
                test_cmd=test_cmd,
                lint_cmd=lint_cmd,
                confidence=0.90,
            )
        )
