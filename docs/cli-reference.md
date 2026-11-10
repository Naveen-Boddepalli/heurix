# CLI Reference

Both `hx` and `heurix` are registered console entrypoints (`heurix.cli:app`). Running `hx` without a subcommand invokes `hx generate`.

## Global options

| Flag | Short | Description |
| --- | --- | --- |
| `--version` | `-v` | Show installed Heurix version and exit. |
| `--help` | | Display command usage and options. |

## `hx generate`

Scans the repository, runs all heuristic detectors, validates synthesized YAML against JSON schemas, and writes or non-destructively merges target files.

```bash
hx generate [OPTIONS]
```

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--path <dir>` | `-p` | `.` | Root directory of the repository to scan. |
| `--explain / --no-explain` | | `True` | Print the step-by-step heuristic reasoning tree. |
| `--dry-run` | | `False` | Preview generated outputs without modifying disk. |
| `--diff` | `-d` | `False` | Display a colorized diff of proposed changes. |
| `--yes` | `-y` | `False` | Non-interactive mode; apply merged changes without prompts. |
| `--k8s / --no-k8s` | | `True` | Synthesize Kubernetes manifests when containerized or framework-backed. |

When an existing file conflicts with newly synthesized content (in interactive mode without `--yes` or `--dry-run`), Heurix prompts for resolution:
- **Apply merged changes** (`SmartMerger` AST round-trip merge)
- **Preview diff**
- **Backup & overwrite** (`.bak` copy created first)
- **Skip file**

## `hx diff`

Shorthand for `hx generate --dry-run --diff --yes --no-explain`. Compares existing YAML files on disk with the synthesized & smart-merged output without writing changes.

```bash
hx diff --path . --k8s
```

## `hx check`

Continuous drift detection. Scans the codebase and checks whether `.github/workflows/ci.yml`, `.github/dependabot.yml`, and configured manifests match current repository dependencies, runtime pins, and package managers.

```bash
hx check [--path .]
```

**Exit codes:**
- `0`: Zero drift detected — workflows match codebase IR.
- `1`: Drift detected (e.g., missing `postgres`/`redis` service container, mismatched runtime version, missing `setup-uv`, or missing workflow files).

Ideal for CI pipelines and Git pre-commit hooks.

## `hx scan`

Scans the codebase and prints the strongly-typed `ProjectContext` Intermediate Representation (IR) as formatted JSON. Useful for debugging detector output or piping repository facts into downstream automation.

```bash
hx scan [--path .]
```

## `hx init`

Creates a `.heurix.toml` policy configuration file in the repository root with `[engine]`, `[ci]`, and `[overrides]` sections.
