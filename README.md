# Heurix (`hx`)

> **Deterministic Codebase Scanner & Automated YAML Synthesizer**  
> *100% Deterministic • Offline-Capable • Deep Heuristic Analysis • Non-Destructive AST Smart Merge*

---

## Overview

**Heurix** (CLI alias: `hx`) is an offline-capable, pure-logic codebase scanner and infrastructure YAML synthesizer. It inspects `.gitignore`-filtered repository files once via `RepoIndexer` into a strongly-typed Pydantic `ProjectContext` Intermediate Representation (IR), cross-references lockfiles, manifests, Dockerfiles, compose configurations, `.env` templates, and cloud deployment targets, and deterministically synthesizes schema-validated CI/CD workflows, Dependabot maintenance files, and Kubernetes manifests.

### Why Pure Logic?
- **100% Deterministic & Reproducible:** No LLM hallucinations, non-determinism, or stale action versions.
- **Instantaneous & Offline:** Runs locally in milliseconds without network calls or API keys.
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
- **Continuous Integration (`.github/workflows/ci.yml`):** Runs the test suite on pull requests and pushes to `main`.
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

### 3. `hx check` (Continuous Drift Detection)
Verifies structurally whether `.github/workflows/ci.yml` and `.github/dependabot.yml` match current codebase dependencies, pinned versions, backing services, and package managers. Exits with code `0` if synchronized, or `1` if drift is detected (ideal for CI and Git pre-commit hooks):
```bash
hx check
```

### 4. `hx scan`
Inspect the strongly-typed `ProjectContext` Intermediate Representation (IR) as JSON:
```bash
hx scan
```

### 5. `hx init` & `.heurix.toml` Policy Overrides
Initialize an optional `.heurix.toml` policy file for custom runners, synthesizer toggles, action SHA pinning, or version overrides:
```bash
hx init
```

Supported `.heurix.toml` sections:
- `[engine]`: `runner` (e.g., `"ubuntu-latest"`), `non_destructive` (`true` / `false`)
- `[ci]`: `include_dependabot`, `include_k8s`, `default_branch`, `pin_actions`, `action_shas` (40-char commit SHA mapping)
- `[overrides]`: explicit language runtime pins (`python = "3.12"`, `node = "20.x"`, etc.)

---

## Deep Heuristic Capabilities

1. **Weighted Polyglot Ecosystem Detection:** Scores root manifests and source file counts across Python, Node.js/TypeScript, Rust, Go, and C/C++ so primary language selection is deterministic and resilient to polyglot repos.
2. **Exact Version Pinning:** Discovers runtime pins from `.python-version`, `.tool-versions`, `pyproject.toml`, `.nvmrc`, `.node-version`, `package.json`, `rust-toolchain.toml`, `go.mod`, and `CMakeLists.txt` (`CMAKE_CXX_STANDARD`).
3. **Lockfile & Virtualenv-Aware Commands:** Selects install, lint, build, and test commands plus caching for `uv` (`uv run ...`), `poetry` (`poetry run ...`), `pipenv`, `pip`, `pnpm`, `yarn`, `bun`, `npm`, `cargo`, `go`, `cmake`, `conan`, `vcpkg`, and `make` (guarding `Makefile` detection so non-C/C++ repos are never misclassified, and sequencing `clang-tidy` after CMake builds only when `.clang-tidy` exists).
4. **Automatic Backing Service Provisioning:** Infers `postgres`, `redis`, and `mongodb` from dependency manifests (`psycopg2`, `asyncpg`, `prisma`, `ioredis`, `mongoose`, etc.) and external `docker-compose.yml` services (skipping local `build:` app containers) to configure GitHub Actions `services:` with health checks and ports.
5. **Environment & Secret Isolation:** Parses `.env.example` / `.env.template` / `.env.sample` / `.env.dist` / `.env.local.example`, separating non-sensitive defaults (`env:` and `k8s/configmap.yaml`) from sensitive keys (`test_secrets` wired to `${{ secrets.KEY }}`, `deployment_secrets` isolated to deploy jobs).
6. **Cloud Deployment Target Detection (`CloudDetector`):** Detects **Vercel** (`vercel.json`, `.vercel`, serverless `api/` routes) and **Firebase** (`firebase.json`, `.firebaserc` project ID and features), wiring required secrets and generating conditional `deploy_vercel` / `deploy_firebase` jobs.
7. **Monorepo Topology:** Detects `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, and `package.json` `workspaces`, enumerating sub-packages and adding Dependabot entries.
8. **Hardened Kubernetes & Kind Manifests (`k8s/`):** Parses `Dockerfile` (`EXPOSE`, final-stage base image, build target, `HEALTHCHECK`) and framework defaults (`FastAPI` `8000`, `Next.js`/`Express` `3000`, `Streamlit` `8501` with HTTP `/_stcore/health` readiness probe) to generate `k8s/deployment.yaml` (with `envFrom` referencing `configmap.yaml` and `optional: true` secrets), `k8s/service.yaml`, `k8s/ingress.yaml` (`ingressClassName: nginx`), `k8s/configmap.yaml`, and `k8s/kind-config.yaml` (with `ingress-ready=true` and host ports `80`/`443`).
9. **Maintenance Automation:** Synthesizes `.github/dependabot.yml` covering `github-actions` and every detected package and container ecosystem.

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
│       │   └── drift.py            # Structural AST drift detection engine
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
└── tests/                          # Full test suite (85 tests across 7 test modules)
```

---

## Running Tests & Site Build

```bash
# Run full test suite (85 tests)
.venv/bin/pytest -v

# Check repository CI drift
.venv/bin/hx check

# Build docs & interactive playground locally
make site-build
```
