"""
Tests for the sandboxed Jinja2 templating engine, SafeFileSystemLoader, YAML filters, and packaging.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from jinja2 import PackageLoader, StrictUndefined
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


def test_templating_choice_loader_and_sandbox_blocks_escapes(tmp_path: Path) -> None:
    from heurix.synthesizers.templating import SafeFileSystemLoader, create_template_environment

    # Verify pyproject.toml declares jinja2>=3.1.6 and package-data for templates/**/*.j2
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps = pyproject_data["project"]["dependencies"]
    assert any(d.lower().startswith("jinja2>=3.1.6") for d in deps), f"Missing jinja2>=3.1.6 in {deps}"
    pkg_data = pyproject_data["tool"]["setuptools"]["package-data"]["heurix"]
    assert "templates/**/*.j2" in pkg_data

    # Verify bundled PackageLoader fallback and ImmutableSandboxedEnvironment settings
    env = create_template_environment()
    assert isinstance(env, ImmutableSandboxedEnvironment)
    assert env.autoescape is False
    assert env.undefined is StrictUndefined
    assert env.trim_blocks is True
    assert env.lstrip_blocks is True
    assert env.keep_trailing_newline is True

    # Render bundled macros/actions.j2 under StrictUndefined with minimal and full step fields
    macro_wrapper = env.from_string(
        '{% from "macros/actions.j2" import render_step %}\n'
        'steps:\n'
        '{{ render_step(s1) }}'
        '{{ render_step(s2, base_indent=6) }}'
        '{{ render_step(s3) }}'
    )
    rendered = macro_wrapper.render(
        s1={
            "name": "Checkout repository",
            "uses": "actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11",
            "uses_comment": "v4",
        },
        s2={
            "id": "unit",
            "name": "Run checks",
            "if": "github.ref == 'refs/heads/main' && github.event_name == 'push'",
            "working-directory": "apps/api",
            "shell": "bash",
            "continue-on-error": False,
            "timeout-minutes": 15,
            "run": "pytest -q && ruff check .",
        },
        s3={
            "working_directory": "packages/core",
            "continue_on_error": True,
            "timeout_minutes": 5,
            "run": "echo ok",
        },
    )
    assert "uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4" in rendered
    assert "&&" in rendered
    assert "&amp;&amp;" not in rendered
    assert "&#39;" not in rendered
    assert "working-directory: apps/api" in rendered
    assert "continue-on-error: false" in rendered
    assert "timeout-minutes: 15" in rendered
    assert "      - working-directory: packages/core" in rendered
    assert "continue-on-error: true" in rendered

    # StrictUndefined must still trigger on genuine missing variables
    with pytest.raises(UndefinedError):
        env.from_string("{{ missing_var }}").render()

    # Verify ChoiceLoader local override + PackageLoader macro fallback
    repo = tmp_path / "repo"
    local_tpl_dir = repo / ".heurix" / "templates" / "workflows"
    local_tpl_dir.mkdir(parents=True)
    (local_tpl_dir / "custom.yml.j2").write_text(
        '{% from "macros/actions.j2" import render_step %}\n'
        'jobs:\n'
        '  test:\n'
        '    steps:\n'
        '{{ render_step(step) }}',
        encoding="utf-8",
    )
    repo_env = create_template_environment(repo_root=repo)
    assert isinstance(repo_env.loader.loaders[0], SafeFileSystemLoader)
    custom_out = repo_env.get_template("workflows/custom.yml.j2").render(
        step={"name": "Custom", "uses": "actions/checkout@v4"}
    )
    assert "      - name: Custom" in custom_out
    assert "        uses: actions/checkout@v4" in custom_out

    # Verify explicit relative templates_dir inside repo_root works and takes precedence
    alt_dir = repo / "custom_templates" / "macros"
    alt_dir.mkdir(parents=True)
    (alt_dir / "actions.j2").write_text(
        "{% macro render_step(step, base_indent=6) %}\n"
        "{{ ' ' * base_indent }}- name: OVERRIDE-{{ step.get('name', 'none') }}\n"
        "{% endmacro %}\n",
        encoding="utf-8",
    )
    alt_env = create_template_environment(repo_root=repo, templates_dir="custom_templates")
    override_out = alt_env.from_string(
        '{% from "macros/actions.j2" import render_step %}{{ render_step({"name": "Step"}) }}'
    ).render()
    assert "OVERRIDE-Step" in override_out

    # SEC-01: Traversal via templates_dir is blocked
    for bad_dir in ("../outside", "/etc", "sub/../../outside"):
        with pytest.raises(ValueError, match="Path traversal security violation"):
            create_template_environment(repo_root=repo, templates_dir=bad_dir)

    # SEC-01: Out-of-repo symlinked template file inside .heurix/templates/ is blocked
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_secret = outside_dir / "secret.j2"
    outside_secret.write_text("leaked: secret", encoding="utf-8")

    symlink_file = repo / ".heurix" / "templates" / "leak.yml.j2"
    symlink_file.symlink_to(outside_secret)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        repo_env.get_template("leak.yml.j2")

    # SEC-01: Out-of-repo symlinked subdirectory inside .heurix/templates/ is blocked
    symlink_subdir = repo / ".heurix" / "templates" / "sub_escape"
    symlink_subdir.symlink_to(outside_dir)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        repo_env.get_template("sub_escape/secret.j2")

    # SEC-01: Out-of-repo symlinked .heurix/templates directory itself is blocked
    repo_dir_escape = tmp_path / "repo_dir_escape"
    (repo_dir_escape / ".heurix").mkdir(parents=True)
    (repo_dir_escape / ".heurix" / "templates").symlink_to(outside_dir)
    with pytest.raises(ValueError, match="Path traversal security violation"):
        create_template_environment(repo_root=repo_dir_escape)

    # T-03-01: ImmutableSandboxedEnvironment blocks dunder, |attr("format") (CVE-2025-27516), and mutation
    with pytest.raises(SecurityError):
        env.from_string("{{ obj.__class__ }}").render(obj="hello")
    with pytest.raises(SecurityError):
        env.from_string('{{ ("{0.__class__}"|attr("format"))(obj) }}').render(obj="hello")
    with pytest.raises(SecurityError):
        env.from_string('{{ ""|attr("__class__") }}').render()
    with pytest.raises(SecurityError):
        env.from_string('{{ items.append("evil") }}').render(items=["a"])
    with pytest.raises(SecurityError):
        env.from_string('{{ mapping.update({"evil": 1}) }}').render(mapping={"a": 1})


class _DummyStepModel(BaseModel):
    python_version: str = Field(alias="python-version")
    cache: bool = True
    empty_ignored: str | None = None


def test_templating_yaml_filters_and_roundtrip_normalization(tmp_path: Path) -> None:
    from heurix.synthesizers.templating import (
        create_template_environment,
        normalize_yaml,
        render_yaml_template,
        yaml_block,
        yaml_inline_list,
        yaml_scalar,
    )

    # Scalar quoting & expression preservation
    assert yaml_scalar("3.10") == "'3.10'"
    assert yaml_scalar("1.20") == "'1.20'"
    assert yaml_scalar("true") == "'true'"
    assert yaml_scalar("false") == "'false'"
    assert yaml_scalar("null") == "'null'"
    assert yaml_scalar("8000") == "'8000'"
    assert yaml_scalar("a: b") == "'a: b'"
    assert yaml_scalar("foo # bar") == "'foo # bar'"
    assert yaml_scalar("") == "''"
    assert yaml_scalar(None) == "null"
    assert yaml_scalar(True) == "true"
    assert yaml_scalar(False) == "false"
    assert yaml_scalar("${{ matrix.python-version }}") == "${{ matrix.python-version }}"
    assert yaml_scalar("pytest && ruff check .") == "pytest && ruff check ."

    # yaml_inline_list formatting
    assert yaml_inline_list(["3.10", "3.11", "1.20"]) == "['3.10', '3.11', '1.20']"
    assert yaml_inline_list(["true", "8000", "${{ matrix.os }}"]) == "['true', '8000', ${{ matrix.os }}]"
    assert yaml_inline_list([]) == "[]"

    # yaml_block recursive Pydantic BaseModel & indentation
    model = _DummyStepModel(**{"python-version": "3.10", "cache": True})
    block_out = yaml_block({"with": model, "items": ["1.20", "true"]}, indent=4)
    assert "    with:\n      python-version: '3.10'\n      cache: true" in block_out
    assert "empty_ignored" not in block_out
    assert "    items:\n      - '1.20'\n      - 'true'" in block_out

    # Registered filters on ImmutableSandboxedEnvironment
    env = create_template_environment()
    assert "yaml_scalar" in env.filters
    assert "yaml_block" in env.filters
    assert "yaml_inline_list" in env.filters

    # Empty & comment-only normalize_yaml edge cases
    assert normalize_yaml("") == ""
    assert normalize_yaml("# comment only\n") == "# comment only\n"

    # Multi-document stream preservation
    multi_doc = (
        "# Synthesized header\n"
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "data:\n"
        "  PORT: '8000'\n"
        "  FLAG: 'true'\n"
        "---\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: demo\n"
    )
    norm_multi = normalize_yaml(multi_doc)
    assert norm_multi.startswith("# Synthesized header\n")
    assert "---\n" in norm_multi
    assert "PORT: '8000'" in norm_multi
    assert "FLAG: 'true'" in norm_multi
    loaded_docs = list(YAML(typ="safe").load_all(norm_multi))
    assert len(loaded_docs) == 2
    assert loaded_docs[0]["data"]["PORT"] == "8000"
    assert loaded_docs[0]["data"]["FLAG"] == "true"

    # Full render_yaml_template with macros/actions.j2: SHA EOL comment, multiline run: |, with/env quoting
    repo = tmp_path / "repo"
    tpl_dir = repo / ".heurix" / "templates" / "workflows"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "sample.yml.j2").write_text(
        '# Synthesized deterministically by Heurix (hx)\n'
        '# Non-destructive updates: preserve blocks marked with # @heurix:preserve\n'
        '{% from "macros/actions.j2" import render_step %}\n'
        'name: CI\n'
        'on:\n'
        '  push:\n'
        '    branches: [main]\n'
        'jobs:\n'
        '  test:\n'
        '    runs-on: {{ runner | yaml_scalar }}\n'
        '    strategy:\n'
        '      fail-fast: false\n'
        '      matrix:\n'
        '        os: {{ matrix_os | yaml_inline_list }}\n'
        '        python-version: {{ python_versions | yaml_inline_list }}\n'
        '    steps:\n'
        '{% for step in steps %}'
        '{{ render_step(step, base_indent=6) }}'
        '{% endfor %}',
        encoding="utf-8",
    )

    checkout_sha = "b4ffde65f46336ab88eb53be808477a3936bae11"
    rendered = render_yaml_template(
        "workflows/sample.yml.j2",
        {
            "runner": "${{ matrix.os }}",
            "matrix_os": ["ubuntu-latest", "macos-latest"],
            "python_versions": ["3.10", "3.12"],
            "steps": [
                {
                    "name": "Checkout repository",
                    "uses": f"actions/checkout@{checkout_sha}",
                    "uses_comment": "v4",
                },
                {
                    "name": "Set up Python",
                    "uses": "actions/setup-python@v5",
                    "with": {"python-version": "3.10", "cache": "pip"},
                },
                {
                    "name": "Multi-line check",
                    "run": "echo start && echo next\n\npytest -q\n",
                    "env": {
                        "APP_PORT": "8000",
                        "FEATURE_FLAG": "true",
                        "GO_MIN": "1.20",
                        "TOKEN_EXPR": "${{ secrets.API_TOKEN }}",
                    },
                },
            ],
        },
        repo_root=repo,
    )

    assert rendered.startswith("# Synthesized deterministically by Heurix (hx)\n")
    assert f"uses: actions/checkout@{checkout_sha}  # v4" in rendered
    assert "python-version: '3.10'" in rendered
    assert "'3.10'" in rendered
    assert "APP_PORT: '8000'" in rendered
    assert "FEATURE_FLAG: 'true'" in rendered
    assert "GO_MIN: '1.20'" in rendered
    assert "echo start && echo next" in rendered
    assert "runs-on: ${{ matrix.os }}" in rendered
    assert "run: |" in rendered

    parsed = YAML(typ="safe").load(rendered)
    assert parsed["jobs"]["test"]["strategy"]["matrix"]["python-version"] == ["3.10", "3.12"]
    multi_step = parsed["jobs"]["test"]["steps"][2]
    assert multi_step["run"] == "echo start && echo next\n\npytest -q\n"
    assert multi_step["env"]["APP_PORT"] == "8000"
    assert multi_step["env"]["FEATURE_FLAG"] == "true"
    assert multi_step["env"]["GO_MIN"] == "1.20"

    raw_unnormalized = render_yaml_template(
        "workflows/sample.yml.j2",
        {
            "runner": "ubuntu-latest",
            "matrix_os": ["ubuntu-latest"],
            "python_versions": ["3.10"],
            "steps": [{"name": "Run", "run": "echo ok"}],
        },
        repo_root=repo,
        normalize=False,
    )
    assert "echo ok" in raw_unnormalized


def test_templating_wheel_packaging_includes_j2_templates(tmp_path: Path) -> None:
    from heurix.synthesizers.templating import create_template_environment

    repo_root = Path(__file__).resolve().parents[1]
    env = create_template_environment()
    pkg_loader = PackageLoader("heurix", "templates")
    source, _, _ = pkg_loader.get_source(env, "macros/actions.j2")
    assert "macro render_step" in source

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "-w",
            str(tmp_path),
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"pip wheel failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    wheels = list(tmp_path.glob("heurix-*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel in {tmp_path}, found {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
        assert any(name.endswith("heurix/templates/macros/actions.j2") for name in names), (
            f"Missing bundled actions.j2 in wheel: {names}"
        )
        metadata_names = [n for n in names if n.endswith("METADATA")]
        assert metadata_names, "Wheel METADATA missing"
        metadata_text = zf.read(metadata_names[0]).decode("utf-8")
        assert "jinja2>=3.1.6" in metadata_text.lower()


