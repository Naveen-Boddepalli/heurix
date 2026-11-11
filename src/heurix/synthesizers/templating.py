"""
Sandboxed Jinja2 template rendering engine and containment-guarded loaders for Heurix.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader, StrictUndefined
from jinja2.loaders import split_template_path
from jinja2.sandbox import ImmutableSandboxedEnvironment
from pydantic import BaseModel
from ruamel.yaml import YAML


def _make_yaml() -> YAML:
    """Create a configured round-trip ruamel.yaml YAML instance."""
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096
    return y


def _to_plain_data(obj: Any) -> Any:
    """Recursively convert Pydantic models and nested structures into plain Python primitives."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, dict):
        return {k: _to_plain_data(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain_data(v) for v in obj]
    return obj


def yaml_scalar(val: Any) -> str:
    """Format a scalar for YAML 1.2 without losing '3.10', '1.20', 'true', or '${{ ... }}'."""
    if val is None:
        return "null"
    y = _make_yaml()
    buf = io.StringIO()
    y.dump(_to_plain_data(val), buf)
    out = buf.getvalue().rstrip("\n")
    if out.endswith("\n..."):
        out = out[:-4]
    elif out == "...":
        out = "''"
    return out


def yaml_block(obj: Any, indent: int = 0) -> str:
    """Dump a mapping or sequence via ruamel.yaml and indent every non-empty line."""
    if obj is None:
        return ""
    y = _make_yaml()
    buf = io.StringIO()
    y.dump(_to_plain_data(obj), buf)
    pad = " " * indent
    return "\n".join((pad + ln if ln else "") for ln in buf.getvalue().rstrip("\n").splitlines())


def yaml_inline_list(seq: Sequence[Any]) -> str:
    """Render an inline YAML sequence with each item formatted via yaml_scalar."""
    plain_seq = _to_plain_data(list(seq))
    return "[" + ", ".join(yaml_scalar(item) for item in plain_seq) + "]"


def normalize_yaml(rendered: str) -> str:
    """Round-trip rendered YAML through ruamel.yaml preserving comments and quotes."""
    if not rendered or not rendered.strip():
        return rendered
    y = _make_yaml()
    docs = [d for d in y.load_all(rendered) if d is not None]
    if not docs:
        return rendered
    buf = io.StringIO()
    if len(docs) == 1:
        y.dump(docs[0], buf)
    else:
        y.dump_all(docs, buf)
    return buf.getvalue()


class SafeFileSystemLoader(FileSystemLoader):
    """FileSystemLoader enforcing strict repo_root containment even across symlinks (SEC-01)."""

    def __init__(
        self,
        searchpath: str | Path,
        repo_root: str | Path,
        encoding: str = "utf-8",
    ) -> None:
        self.repo_root_resolved = Path(repo_root).resolve()
        super().__init__(str(searchpath), encoding=encoding, followlinks=False)

    def get_source(
        self, environment: Any, template: str
    ) -> Tuple[str, str, Callable[[], bool]]:
        pieces = split_template_path(template)
        for searchpath in self.searchpath:
            candidate = Path(searchpath).joinpath(*pieces)
            if not candidate.resolve().is_relative_to(self.repo_root_resolved):
                raise ValueError(
                    f"Path traversal security violation: template '{template}' resolves outside repository root '{self.repo_root_resolved}'"
                )

        contents, filename, uptodate = super().get_source(environment, template)
        resolved = Path(filename).resolve()
        if not resolved.is_relative_to(self.repo_root_resolved):
            raise ValueError(
                f"Path traversal security violation: template '{template}' resolves outside repository root '{self.repo_root_resolved}'"
            )
        return contents, filename, uptodate


def create_template_environment(
    repo_root: Optional[str | Path] = None,
    templates_dir: Optional[str] = None,
) -> ImmutableSandboxedEnvironment:
    """
    Create a hardened ImmutableSandboxedEnvironment with ChoiceLoader.

    Optional repo-local templates (.heurix/templates/ or [engine].templates_dir) are checked
    first via SafeFileSystemLoader after verifying containment within repo_root, falling back
    to bundled PackageLoader("heurix", "templates").
    """
    loaders: List[Any] = []
    explicit_dir = templates_dir.strip() if isinstance(templates_dir, str) and templates_dir.strip() else None

    if repo_root is not None and str(repo_root).strip():
        root_resolved = Path(repo_root).resolve()
        rel_dir = explicit_dir if explicit_dir is not None else ".heurix/templates"
        candidate = root_resolved / rel_dir
        candidate_resolved = candidate.resolve()

        if explicit_dir is not None:
            if not candidate_resolved.is_relative_to(root_resolved):
                raise ValueError(
                    f"Path traversal security violation: templates_dir '{rel_dir}' resolves outside repository root '{repo_root}'"
                )
        elif candidate.exists() or candidate.is_symlink() or not candidate_resolved.is_relative_to(root_resolved):
            if not candidate_resolved.is_relative_to(root_resolved):
                raise ValueError(
                    f"Path traversal security violation: templates_dir '{rel_dir}' resolves outside repository root '{repo_root}'"
                )

        if candidate_resolved.exists() and candidate_resolved.is_dir():
            loaders.append(SafeFileSystemLoader(candidate_resolved, repo_root=root_resolved))
    elif explicit_dir is not None:
        raise ValueError(
            f"Path traversal security violation: templates_dir '{explicit_dir}' cannot be resolved without repo_root"
        )

    loaders.append(PackageLoader("heurix", "templates"))
    env = ImmutableSandboxedEnvironment(
        loader=ChoiceLoader(loaders),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["yaml_scalar"] = yaml_scalar
    env.filters["yaml_block"] = yaml_block
    env.filters["yaml_inline_list"] = yaml_inline_list
    return env


def render_yaml_template(
    template_name: str,
    context_data: Mapping[str, Any],
    *,
    repo_root: Optional[str | Path] = None,
    templates_dir: Optional[str] = None,
    normalize: bool = True,
) -> str:
    """
    Render a Jinja2 YAML template inside ImmutableSandboxedEnvironment and optionally
    normalize the AST via round-trip ruamel.yaml.
    """
    env = create_template_environment(repo_root=repo_root, templates_dir=templates_dir)
    template = env.get_template(template_name)
    plain_context = _to_plain_data(dict(context_data))
    rendered = template.render(**plain_context)
    if normalize:
        return normalize_yaml(rendered)
    return rendered
