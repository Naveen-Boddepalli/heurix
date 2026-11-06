"""
C / C++ Ecosystem Detector.
"""

from __future__ import annotations

from heurix.core.context import LanguageContext, ProjectContext
from heurix.core.indexer import RepoIndexer
from heurix.detectors.base import BaseDetector


class CppDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "C++"

    def detect(self, indexer: RepoIndexer) -> bool:
        indicators = ["CMakeLists.txt", "Makefile", "conanfile.txt", "conanfile.py", "vcpkg.json"]
        return any(indexer.has_file(f) for f in indicators) or bool(indexer.find_files("*.cpp")) or bool(indexer.find_files("*.cc"))

    def analyze(self, indexer: RepoIndexer, context: ProjectContext) -> None:
        context.add_explain("Analyzing C / C++ ecosystem...")

        package_manager = "cmake"
        install_cmd = ""
        build_cmd = "cmake -B build -S . && cmake --build build"
        test_cmd = "ctest --test-dir build --output-on-failure"

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
            install_cmd = "cmake -B build -S ."
            context.add_explain("Detected Build Tool: CMake (via CMakeLists.txt)")
        elif indexer.has_file("Makefile"):
            package_manager = "make"
            install_cmd = ""
            build_cmd = "make"
            test_cmd = "make test"
            context.add_explain("Detected Build Tool: Make (via Makefile)")

        context.languages.append(
            LanguageContext(
                language="cpp",
                runtime_version="latest",
                version_source="system",
                package_manager=package_manager,
                install_cmd=install_cmd or "echo 'No package manager'",
                build_cmd=build_cmd,
                test_cmd=test_cmd,
                lint_cmd="clang-tidy -p build",
                confidence=0.90,
            )
        )
