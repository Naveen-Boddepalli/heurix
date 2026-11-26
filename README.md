# Heurix (`hx`)

> **Deterministic Codebase Scanner & Automated YAML Synthesizer**  
> *100% Deterministic • Offline-Capable • Deep Heuristic Analysis • Non-Destructive AST Smart Merge*

---

## Overview

**Heurix** (CLI alias: `hx`) is an offline-capable, pure-logic codebase scanner and infrastructure YAML synthesizer. It inspects `.gitignore`-filtered repository files once via `RepoIndexer` into a strongly-typed Pydantic `ProjectContext` Intermediate Representation (IR), cross-references lockfiles, manifests, Dockerfiles, compose configurations, `.env` templates, and cloud deployment targets, and deterministically synthesizes schema-validated CI/CD workflows, Dependabot maintenance files, and Kubernetes manifests.

### Why Pure Logic?
- **100% Deterministic & Reproducible:** No LLM hallucinations or non-determinism; vetted action pins with least-privilege `permissions: contents: read` and customizable action versions/commit SHAs via `.heurix.toml`.
- **Instantaneous & Offline:** Runs locally in milliseconds without network calls or API keys. The one exception is `hx pin`, which you run explicitly to resolve action tags to commit SHAs.
- **Non-Destructive AST Smart Merge:** Traverses `ruamel.yaml` ASTs recursively to preserve comments, custom user jobs, triggers, and any step tagged with `# @heurix:preserve` or `# @autoyaml:preserve` across repeated runs.
- **Pre-Flight Schema Validation:** Validates single- and multi-document YAML outputs against JSON schemas (`PreflightValidator`) before writing a single byte to disk, with symlink/path-traversal protection.
- **Structural Drift Detection:** `hx check` parses existing CI workflows and Dependabot configs structurally to detect missing backing services, pinned runtime mismatches, or outdated package manager setup.

### Documentation & Interactive Playground
- **Web Docs & Live Playground:** `https://naveen-boddepalli.github.io/heurix/`
- **LLM Context Index:** `llms.txt` (and `https://naveen-boddepalli.github.io/heurix/llms-full.txt`)
- **Guides & Reference Docs (`docs/`):**
  - `docs/getting-started.md` — installation, first scan, and `.heurix.toml` overrides
  - `docs/heuristics.md` — full matrix for all 8 ecosystem detectors
  - `docs/cli-reference.md` — commands, flags, interactive prompts, and exit codes
  - `docs/smart-merge.md` — `ruamel.yaml` AST merging and `# @heurix:preserve`
  - `docs/kubernetes-and-ci.md` — synthesized GitHub Actions, Dependabot, and `k8s/` outputs
  - `docs/drift-detection.md` — running `hx check` in CI and pre-commit hooks
  - `docs/architecture.md` — unidirectional 5-layer IR architecture

---

## Installation & Deployment

### 1. Install via PyPI
```bash
pip install heurix
# or with pipx for isolated global CLI access (recommended)
pipx install heurix
```

### 2. Standalone One-Line Installer
```bash
curl -fsSL https://raw.githubusercontent.com/Naveen-Boddepalli/heurix/main/install.sh | bash
```

### 3. Docker Container (No Python installation required)
```bash
docker run --rm -v $(pwd):/workspace ghcr.io/naveen-boddepalli/heurix:latest generate
```

### 4. Local Development & Global Shell Alias
Clone the repository and install in editable mode:
```bash
git clone https://github.com/Naveen-Boddepalli/heurix.git
cd heurix
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,build]'
```

To run `hx` from anywhere in your shell, add this to your `~/.zshrc` or `~/.bashrc`:
```bash
alias hx="/path/to/heurix/.venv/bin/hx"
```
Or execute directly from the repository root using `./hx`.

---

## Deployment & CI/CD Pipelines

The repository includes automated build, test, and publishing workflows:
- **Continuous Integration (`.github/workflows/ci.yml`):** On pull requests and pushes to `main`, lints with ruff and runs the test suite with branch coverage (85% floor) on Python 3.10–3.12, plus a job that checks `ruff format` and `mypy`.
- **PyPI Trusted Publishing (`.github/workflows/publish-pypi.yml`):** Builds sdist and wheel distributions and publishes to PyPI via GitHub Actions OIDC trusted publishing on release or `v*.*.*` tag push (plus manual `workflow_dispatch` for TestPyPI/PyPI).
- **Multi-Platform Docker Publishing (`.github/workflows/docker-publish.yml`):** Builds multi-arch (`linux/amd64`, `linux/arm64`) container images and publishes to `ghcr.io/naveen-boddepalli/heurix:latest`.
- **GitHub Pages Docs & Playground (`.github/workflows/pages.yml`):** Syncs `docs/` and `llms.txt`, builds the React + Vite frontend (`site/`), and deploys to GitHub Pages on push to `main`.
- **Production `Dockerfile` & `.dockerignore`:** Multi-stage minimal container runtime with a non-root user and `/workspace` mount point.
- **Homebrew Formula (`packaging/homebrew/heurix.rb`):** Tap-ready formula for `brew install`.
- **`Makefile`:** Developer tasks (`make test`, `make check`, `make build`, `make docker-build`, `make docker-run`, `make site-dev`, `make site-build`, `make clean`).

---

## CLI Commands & Usage

Both `hx` and `heurix` invoke the CLI. Running `hx` with no subcommand runs `hx generate`.

### 1. `hx generate` (or `hx`)
Scans the codebase, runs heuristic detectors, validates synthesized YAML, and writes or non-destructively merges outputs.

```bash
# Scan and generate with step-by-step explainability log
hx generate

# Preview synthesized files without modifying disk (Dry Run)
hx generate --dry-run

# Show colorized terminal diff of proposed changes
hx generate --diff

# Non-interactive mode (auto-apply changes without prompts)
hx generate --yes

# Skip Kubernetes manifest synthesis
hx generate --no-k8s

# Target a specific repository path
hx generate --path /path/to/project
```

When an existing file would change in interactive mode, Heurix lets you choose between applying the AST smart merge, previewing the colorized diff (and re-prompting), creating a `.bak` backup before overwriting, or skipping the file.

### 2. `hx diff`
Compare existing repository configs against synthesized & smart-merged outputs without writing changes:
```bash
hx diff
```

### 3. `hx check` (Continuous Drift Detection & Security Audit)
Verifies structurally whether `.github/workflows/ci.yml` and `.github/dependabot.yml` match current codebase dependencies, pinned versions, backing services, and package managers. Exits with code `0` if synchronized, or `1` if drift is detected (ideal for CI and Git pre-commit hooks):
```bash
hx check
```

Add `--security` to audit every workflow for excessive token permissions, unpinned third-party actions, `pull_request_target`, template injection and persisted checkout credentials (rule IDs match zizmor). `--format json` or `--format sarif` prints a machine-readable report; SARIF uploads to GitHub code scanning:
```bash
hx check --security
hx check --security --format sarif > heurix.sarif
```

### 4. `hx pin`
Pin every workflow action to a full commit SHA, keeping the tag as a comment that Dependabot uses to update it (`uses: actions/checkout@<sha>  # v7`). Refs are resolved with `git ls-remote`, so no token is needed. In repositories that use a GitHub Actions lockfile (`.github/workflows/actions.lock`), use `gh actions-lock` instead; `hx generate` keeps locked refs and `hx check` reports actions missing from the lockfile.
```bash
hx pin --dry-run
hx pin
```

### 5. `hx scan`
Inspect the strongly-typed `ProjectContext` Intermediate Representation (IR) as JSON:
```bash
hx scan
```

### 6. `hx init` & `.heurix.toml` Policy Overrides
Initialize an optional `.heurix.toml` policy file for custom runners, synthesizer toggles, action SHA pinning, or version overrides:
```bash
hx init
```

Supported `.heurix.toml` sections:
- `[engine]`: `runner` (e.g., `"ubuntu-latest"`), `non_destructive` (`true` / `false`)
- `[ci]`: `include_dependabot`, `include_k8s`, `default_branch`, `pin_actions`, `action_shas` (40-char commit SHA mapping), `paths` / `paths_ignore` (trigger path filters for `push` and `pull_request`)
- `[overrides]`: explicit language runtime pins (`python = "3.12"`, `node = "20.x"`, etc.)

---

## Deep Heuristic Capabilities

1. **Weighted Polyglot Ecosystem Detection:** Scores root manifests and source file counts across Python, Node.js/TypeScript, Rust, Go, and C/C++ so primary language selection is deterministic and resilient to polyglot repos.
2. **Exact Version Pinning:** Discovers runtime pins from `.python-version`, `.tool-versions`, `pyproject.toml`, `.nvmrc` (preserving exact semver pins), `.node-version`, `package.json`, `rust-toolchain.toml`, `go.mod`, and `CMakeLists.txt` (`CMAKE_CXX_STANDARD`).
3. **Lockfile & Virtualenv-Aware Commands:** Selects install, lint, build, and test commands plus caching for `uv` (`uv run ...`), `poetry` (`poetry run ...`), `pipenv`, `pip`, `pnpm`, `yarn`, `bun`, `npm`, `cargo`, `go`, `cmake`, `conan`, `vcpkg`, and `make` (guarding `Makefile` detection so non-C/C++ repos are never misclassified, and sequencing `clang-tidy` after CMake builds only when `.clang-tidy` exists).
4. **Automatic Backing Service Provisioning:** Infers `postgres`, `redis`, and `mongodb` from dependency manifests (Python: `psycopg2`, `asyncpg`, `pymongo`, `motor`, `mongoengine`, `beanie`; Node.js: `prisma`, `ioredis`, `mongoose`, `mongodb`) and external `docker-compose.yml` services, aligning test credentials and configuring health checks and ports.
5. **Environment & Secret Isolation:** Parses `.env.example` / `.env.template` / `.env.sample` / `.env.dist` / `.env.local.example`, separating non-sensitive defaults (`env:` and `k8s/configmap.yaml`) from sensitive keys (`test_secrets` wired to `${{ secrets.KEY }}`, `deployment_secrets` isolated to deploy jobs), and enforcing top-level `permissions: contents: read`.
6. **Cloud Deployment Target Detection (`CloudDetector`):** Detects **Vercel** (`vercel.json`, `.vercel`, serverless `api/` routes) and **Firebase** (`firebase.json`, `.firebaserc` project ID and features), wiring required secrets and generating conditional `deploy_vercel` / `deploy_firebase` jobs.
7. **Monorepo Topology:** Detects `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, and `package.json` `workspaces`, enumerating sub-packages and adding Dependabot entries.
8. **Hardened Kubernetes & Kind Manifests (`k8s/`):** Generates production-hardened manifests with pod and container `securityContext` (`runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `drop: [ALL]` capabilities), `k8s/deployment.yaml`, `k8s/service.yaml`, `k8s/ingress.yaml` (`ingressClassName: nginx`), `k8s/configmap.yaml`, `k8s/secret.yaml`, and `k8s/kind-config.yaml`.
9. **Maintenance & Safety Controls:** Synthesizes `.github/dependabot.yml` covering `github-actions` and every detected ecosystem, with empty directory guards that prevent generating hollow workflows on repos with no code.

---

## Project Structure

```text
heurix/
├── pyproject.toml                  # Build & dependency metadata (scripts: hx, heurix)
├── Makefile                        # Dev, test, Docker, build, and docs site tasks
├── Dockerfile                      # Multi-stage production container image
├── heurix.md                       # Master architecture & product plan
├── llms.txt                        # LLM-friendly project index
├── hx                              # Direct executable wrapper
├── docs/                           # Guides, CLI reference, and architecture docs
├── site/                           # Interactive Vite + React docs & playground frontend
├── .github/workflows/              # ci.yml, pages.yml, docker-publish.yml, publish-pypi.yml
├── src/
│   └── heurix/
│       ├── cli.py                  # Typer CLI entrypoint & path-safe file writer
│       ├── core/
│       │   ├── context.py          # Pydantic ProjectContext IR & DeploymentTarget models
│       │   ├── indexer.py          # .gitignore-aware repo indexer & language scorer
│       │   ├── merger.py           # ruamel.yaml recursive AST merge & comment preservation
│       │   ├── validator.py        # Multi-doc pre-flight JSON schema validator
│       │   ├── drift.py            # Structural AST drift detection engine
│       │   ├── lockfile.py         # GitHub Actions workflow lockfile (actions.lock) reader
│       │   └── pinning.py          # hx pin: resolve action tags to commit SHAs
│       ├── detectors/              # Modular language, infra & cloud providers
│       │   ├── base.py
│       │   ├── python_detector.py
│       │   ├── node_detector.py
│       │   ├── rust_detector.py
│       │   ├── go_detector.py
│       │   ├── cpp_detector.py
│       │   ├── docker_detector.py
│       │   ├── env_detector.py
│       │   └── cloud_detector.py
│       ├── synthesizers/           # Deterministic YAML generators
│       │   ├── base.py
│       │   ├── github_actions.py
│       │   ├── maintenance.py
│       │   └── kubernetes.py
│       └── ui/
│           ├── console.py          # Rich explain-tree and summary tables
│           ├── differ.py           # Colorized terminal diff viewer
│           └── prompts.py          # Interactive conflict resolution prompts
└── tests/                          # pytest suite (coverage gated in CI)
```

---

## Running Tests, Quality Gates & Site Build

```bash
# Run full test suite
.venv/bin/pytest -v

# Run every CI gate: ruff lint, ruff format check, mypy, and tests with coverage (85% floor)
make qa

# Check repository CI drift
.venv/bin/hx check

# Build docs & interactive playground locally
make site-build
```
