# Getting started

Heurix (`hx`) is a deterministic codebase scanner and automated YAML synthesizer. It inspects your repository's files, lockfiles, runtime pins, Dockerfiles, and dependencies in milliseconds—without network calls or LLM hallucinations—and synthesizes production-ready GitHub Actions workflows, Dependabot maintenance files, and Kubernetes manifests.

## Install

Install with `pipx` (recommended for isolated global CLI usage) or `pip`:

```bash
pipx install heurix
# or
pip install heurix
```

Or install via the standalone shell script:

```bash
curl -fsSL https://raw.githubusercontent.com/Naveen-Boddepalli/heurix/main/install.sh | bash
```

Or run directly via Docker without installing Python:

```bash
docker run --rm -v "$(pwd):/workspace" ghcr.io/naveen-boddepalli/heurix:latest generate --dry-run
```

Requires Python `>= 3.10` when installed from PyPI.

## First scan

Inspect what Heurix infers about your project before writing any files:

```bash
hx scan
```

This prints the strongly-typed `ProjectContext` Intermediate Representation (IR) as JSON, including detected languages, pinned versions, package managers, backing services, container configurations, cloud deployment targets, required secrets, and the human-readable `explain_log`.

## Synthesize configurations

Run a dry-run preview first to see the reasoning tree and generated files:

```bash
hx generate --dry-run
```

Preview a colorized terminal diff against existing files:

```bash
hx generate --diff
```

Generate and merge configurations interactively (or pass `--yes` for non-interactive CI/automation):

```bash
hx generate
# or
hx generate --yes
```

## Policy overrides (`.heurix.toml`)

Heurix works with zero configuration by default. To enforce team-wide overrides (such as always running on `ubuntu-24.04-arm` or skipping Kubernetes generation), initialize a `.heurix.toml` file:

```bash
hx init
```

Example `.heurix.toml`:

```toml
[engine]
runner = "ubuntu-latest"
non_destructive = true

[ci]
include_dependabot = true
include_k8s = true

[overrides]
# python = "3.12"
# node = "20.x"
```

## Preserving custom YAML edits

Whenever Heurix updates an existing `.github/workflows/ci.yml`, it uses `ruamel.yaml` round-trip AST merging rather than overwriting the file. Custom jobs (such as Slack notifications or deployment hooks) and any step marked with `# @heurix:preserve` are left untouched:

```yaml
      - name: Notify team on failure # @heurix:preserve
        if: failure()
        uses: slackapi/slack-github-action@v1
```
