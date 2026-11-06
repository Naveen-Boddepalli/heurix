# Heurix (`hx`)

> **Deterministic Codebase Scanner & Automated YAML Synthesizer**  
> *100% Deterministic • Offline-Capable • Deep Heuristic Analysis • Non-Destructive Smart Merge*

---

## Overview

**Heurix** (CLI alias: `hx`) is an intelligent, pure-logic codebase scanner and infrastructure synthesizer. It cross-references repository files, lockfiles, dependency manifests, Dockerfiles, and compose configurations to infer intent and topology—then deterministically synthesizes production-ready CI/CD workflows, Dependabot maintenance files, and Kubernetes manifests.

### Why Pure Logic?
- **100% Deterministic & Reproducible:** No hallucinations, non-determinism, or outdated action versions.
- **Instantaneous & Offline:** Runs in milliseconds without network calls or API keys.
- **Non-Destructive Smart Merge:** Uses AST round-trip merging (`ruamel.yaml`) to preserve custom steps, Slack notifications, and blocks tagged with `# @heurix:preserve`.
- **Pre-Flight Validation:** Validates all generated YAML against JSON schemas before writing to disk.

---

## Quick Start & CLI Alias

The package is installed in the local environment and provides the `hx` and `heurix` command-line tools.

### Set up Global Shell Alias

To use `hx` from any directory in your shell, add this to your `~/.zshrc` (or `~/.bashrc`):

```bash
alias hx="/Users/boddepallinaveen/Desktop/heurix/.venv/bin/hx"
```

Or run directly from the workspace:
```bash
./hx --help
```

---

## CLI Commands & Usage

### 1. `hx generate` (or simply `hx`)
Scans the current codebase, runs heuristic detectors, and synthesizes YAML configurations.

```bash
# Scan and generate with step-by-step explainability log
hx generate

# Preview changes without modifying files (Dry Run)
hx generate --dry-run

# Show colorized terminal diff of proposed changes
hx generate --diff

# Non-interactive mode (automatically apply changes)
hx generate --yes

# Target a specific repository path
hx generate --path /path/to/project
```

### 2. `hx diff`
Compare the current repository state against synthesized configurations:
```bash
hx diff
```

### 3. `hx check` (Continuous Drift Detection)
Verifies if existing CI/CD workflows match current codebase dependencies and configurations. Exits with return code `0` if clean, or `1` if drift is detected (ideal for Git pre-commit hooks and CI pipelines):
```bash
hx check
```

### 4. `hx scan`
Inspect the Intermediate Representation (IR) extracted by the heuristics engine:
```bash
hx scan
```

### 5. `hx init`
Initialize an optional `.heurix.toml` policy file for team-wide overrides:
```bash
hx init
```

---

## Deep Heuristic Capabilities

1. **Exact Version Pinning:** Discovers exact language versions from `.python-version`, `.nvmrc`, `.node-version`, `rust-toolchain.toml`, `go.mod`, or `pyproject.toml`.
2. **Lockfile & Cache Fingerprinting:** Selects optimal install commands and cache actions for `uv`, `poetry`, `pip`, `pnpm`, `yarn`, `bun`, `npm`, `cargo`, and `go`.
3. **Automatic Backing Service Provisioning:** Infers database and cache needs (`postgres`, `redis`, `mongodb`) from dependency manifests (`psycopg2`, `prisma`, `ioredis`, `mongoose`) and configures GitHub Actions `services:` with health checks and ports.
4. **Environment & Secrets Wiring:** Parses `.env.example` to wire default environment variables and map sensitive keys (`STRIPE_SECRET_KEY`, `AUTH_TOKEN`) to `${{ secrets.KEY }}`.
5. **Monorepo Topology:** Detects `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, and sub-packages.
6. **Container Orchestration:** Parses `Dockerfile` (`EXPOSE`, base images, health checks) to generate Kubernetes `Deployment`, `Service`, and `Ingress` manifests.
7. **Maintenance Automation:** Synthesizes `.github/dependabot.yml` covering every package ecosystem detected in the repo.

---

## Project Structure

```text
heurix/
├── pyproject.toml              # Build & dependency metadata (scripts: hx, heurix)
├── heurix.md                   # Master architecture & product plan
├── hx                          # Direct executable wrapper
├── src/
│   └── heurix/
│       ├── cli.py              # Typer CLI entrypoint
│       ├── core/
│       │   ├── context.py      # Pydantic ProjectContext IR
│       │   ├── indexer.py      # .gitignore-aware repo indexer (<50ms)
│       │   ├── merger.py       # ruamel.yaml AST smart merge & comment preservation
│       │   ├── validator.py    # Pre-flight JSON schema validator
│       │   └── drift.py        # Continuous drift detection engine
│       ├── detectors/          # Modular language & stack providers
│       │   ├── python_detector.py
│       │   ├── node_detector.py
│       │   ├── rust_detector.py
│       │   ├── go_detector.py
│       │   ├── cpp_detector.py
│       │   ├── docker_detector.py
│       │   └── env_detector.py
│       ├── synthesizers/       # Deterministic YAML generators
│       │   ├── github_actions.py
│       │   ├── maintenance.py
│       │   └── kubernetes.py
│       └── ui/
│           ├── console.py      # Rich explain-tree and summary tables
│           ├── differ.py       # Colorized terminal diff viewer
│           └── prompts.py      # Interactive ambiguity resolution
└── tests/                      # Full test suite (15 unit & integration tests)
```

---

## Running Tests

```bash
.venv/bin/pytest -v
```
