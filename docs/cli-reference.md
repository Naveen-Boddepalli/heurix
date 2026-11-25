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
hx check [--path .] [--security] [--format text|json|sarif]
```

- `--security`: also audit every workflow for security issues: excessive token permissions, third-party actions not pinned to a SHA, `pull_request_target` and `workflow_run`, checking out pull request code in them, template injection, persisted checkout credentials and `secrets: inherit`. See [the rule list](drift-detection.md#security-audit-hx-check---security).
- `--format` / `-f`: `text` (default), `json`, or `sarif` for GitHub code scanning. In `json` and `sarif` mode only the report goes to stdout. See [machine-readable reports](drift-detection.md#machine-readable-reports).

**Exit codes:**
- `0`: Zero drift detected — workflows match codebase IR (and, with `--security`, no security findings).
- `1`: Drift detected (e.g., missing `postgres`/`redis` service container, mismatched runtime version, missing `setup-uv`, missing workflow files, or an action missing from `.github/workflows/actions.lock`), or a security finding with `--security`.
- `2`: Unknown `--format`.

Ideal for CI pipelines and Git pre-commit hooks.

## `hx pin`

Pins every action in `.github/workflows/*.yml` to a full commit SHA, keeping the original ref as a comment that Dependabot and Renovate use to update the pin:

```yaml
# before
      - uses: actions/checkout@v7
# after
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7
```

```bash
hx pin [--path .] [--dry-run]
```

- Refs are resolved with `git ls-remote` against github.com, so `git` must be installed. No token is needed and there is no API rate limit. This is the only Heurix command that uses the network.
- Files are edited line by line: comments, quoting and layout are kept, and an existing comment on the line follows the ref (`# v7 your note`).
- Refs that are already SHAs, local actions (`./`), `docker://` images and `${{ }}` expressions are left alone. `dtolnay/rust-toolchain` is skipped, because its ref selects the toolchain.
- If `.github/workflows/actions.lock` exists, `hx pin` changes nothing and points you to `gh actions-lock`, since the lockfile holds the pins.
- Later `hx generate` runs keep the pins and their comments.

**Exit codes:**
- `0`: Every ref was pinned, or was already pinned.
- `1`: A ref couldn't be resolved (the rest are still pinned and written), or the repository uses a lockfile.

## `hx scan`

Scans the codebase and prints the strongly-typed `ProjectContext` Intermediate Representation (IR) as formatted JSON. Useful for debugging detector output or piping repository facts into downstream automation.

```bash
hx scan [--path .]
```

## `hx init`

Creates a `.heurix.toml` policy configuration file in the repository root with `[engine]`, `[ci]`, and `[overrides]` sections.
