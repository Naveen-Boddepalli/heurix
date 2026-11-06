# Codebase Scanner & Automated YAML Synthesizer: Master Architecture & Product Plan

## 1. Executive Summary & Core Philosophy

Infrastructure and CI/CD configuration should be **deterministic, reproducible, and transparent**. While Large Language Models (LLMs) can draft configurations, they suffer from non-determinism, hallucinations, outdated action versions, and latency/privacy concerns. 

By combining **Deep Static Configuration Analysis**, a **Heuristic Rule Engine**, and **Stateful Round-Trip YAML Synthesis**, we can build a pure-logic package that feels as magical as an AI assistant while remaining $100\%$ deterministic, offline-capable, and instantaneous.

---

## 2. Deep Industry Research: How the Best Tools Work

To build a best-in-class tool, we synthesize patterns from five industry-leading open-source projects:

| Tool | Core Mechanism | What We Adopt |
| :--- | :--- | :--- |
| **Nixpacks (by Railway)** | Deterministic build-plan generator written in Rust. Uses modular "Providers" that inspect files, lockfiles, and engines to build an execution graph. | **Provider-Based Detection Lifecycle:** Each language/framework is an isolated provider with `detect()` and `plan()` methods. |
| **Projen (by AWS)** | Manages project configuration files via synthesized state. Tracks which lines are machine-generated vs. user-managed. | **Non-Destructive Synthesis:** Never blindly overwrite a user's manual YAML edits; use managed blocks and AST merging. |
| **Cloud Native Buildpacks** | Uses a strict `detect` -> `analyze` -> `build` phase contract with weighted priority rules. | **Confidence Scoring:** When multiple frameworks or test runners are detected, score them and resolve conflicts predictably. |
| **GitHub Linguist** | Uses file extensions, shebangs, modelines, and vendor filtering to map repository composition. | **Fast File-Tree Indexing:** Ignore `.git`, `node_modules`, `venv`, and `target` immediately using `.gitignore`-aware traversal. |
| **Actionlint / Kubeconform** | Static analysis and JSON Schema validation for workflows and Kubernetes manifests. | **Pre-Flight Validation:** Validate every generated YAML against official schemas before writing a single byte to disk. |

---

## 3. Achieving "LLM-Level" Intelligence with Pure Logic

An ordinary scaffolding tool only checks if `package.json` exists. A tool that feels "intelligent" cross-references multiple files in the repository to infer intent, environment needs, and topology.

### 3.1. The Deep Heuristic Matrix

1. **Exact Version Pinning (Zero Hardcoding)**
   * **Signal:** Inspects `.nvmrc`, `.node-version`, `.python-version`, `rust-toolchain.toml`, `go.mod` (`go 1.22`), or `pyproject.toml` (`requires-python = ">=3.11"`).
   * **Action:** Injects the exact version (or a matrix of supported versions) into `actions/setup-node` or `actions/setup-python` instead of guessing a default version.

2. **Package Manager & Lockfile Fingerprinting**
   * **Signal:** Distinguishes between `package-lock.json` (`npm ci`), `yarn.lock` (`yarn install --frozen-lockfile`), `pnpm-lock.yaml` (`pnpm i --frozen-lockfile`), `poetry.lock`, `uv.lock`, and `Pipfile.lock`.
   * **Action:** Selects the exact installation command and configures the corresponding build cache (`cache: 'pnpm'`, ` astral-sh/setup-uv`, etc.).

3. **Service Container Auto-Provisioning (Database & Cache Inference)**
   * **Signal:** Cross-references `docker-compose.yml` services OR dependency files (`psycopg2`, `redis`, `mongoose`, `prisma/schema.prisma`) against test scripts.
   * **Action:** Automatically injects GitHub Actions `services:` blocks (e.g., spinning up a `postgres:16-alpine` or `redis:7` container with health checks and matching ports) during the CI test job.

4. **Environment Variable & Secret Discovery**
   * **Signal:** Parses `.env.example`, `.env.template`, `settings.py` (`os.environ.get(...)`), or `Dockerfile` (`ENV` / `ARG`).
   * **Action:** Populates an `env:` block in the generated YAML mapping non-sensitive defaults from `.env.example` and wiring sensitive keys to `${{ secrets.KEY_NAME }}` with inline reminder comments.

5. **Monorepo & Workspace Topology Detection**
   * **Signal:** Detects `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`, or multiple sub-directories containing independent `package.json`, `Cargo.toml`, or `CMakeLists.txt` files.
   * **Action:** Generates path-filtered workflows (`on: push: paths: ['apps/web/**']`) or dynamic build matrices so CI only builds and tests affected packages.

6. **Container & Orchestration Synchronization**
   * **Signal:** Parses `Dockerfile` AST for `EXPOSE <port>`, `ENTRYPOINT`, multi-stage build targets (`FROM ... AS builder`), and health check routes.
   * **Action:** Generates Kubernetes `deployment.yaml`, `service.yaml`, and `ingress.yaml` with the exact `containerPort`, `livenessProbe`, and resource requests tailored to the runtime (e.g., higher memory baseline for JVM vs. Go binaries).

7. **Automated Maintenance & Hygiene Workflows**
   * **Signal:** Scans all ecosystems present in the repo plus existing GitHub Actions versions.
   * **Action:** Synthesizes `.github/dependabot.yml` (or `renovate.json`) covering every detected package ecosystem (`pip`, `npm`, `docker`, `github-actions`), alongside `release-please` or stale-issue maintenance workflows.

---

## 4. Best-in-Class User Experience (DX / UX) Features

A command-line developer tool succeeds or fails on trust and ergonomics. Writing files into a user's repository is invasive; the UX must make the user feel in complete control.

### 4.1. Explainable Reasoning Log (`--explain`)
Instead of silently dropping a 150-line YAML file, the CLI prints a transparent, step-by-step reasoning tree using `Rich`:
```text
🔍 Scanning repository at ./my-project...
  ├─ ✔ Detected Python 3.12 (via .python-version)
  ├─ ✔ Detected Package Manager: uv (via uv.lock)
  ├─ ✔ Detected Framework: FastAPI (via pyproject.toml)
  ├─ ✔ Detected Test Runner: pytest + coverage (via pyproject.toml [tool.pytest])
  ├─ ✔ Detected Backing Services: PostgreSQL 15, Redis 7 (via docker-compose.yml)
  └─ ✔ Detected Container Port: 8000 (via Dockerfile EXPOSE)

✨ Synthesizing .github/workflows/ci.yml (Confidence: 98%)
```

### 4.2. Interactive Ambiguity Resolution (Hybrid TUI)
When heuristics hit an ambiguous state (e.g., both `jest` and `playwright` are installed, or a user asks for CD without specifying AWS, GCP, or Kubernetes), the CLI launches an interactive keyboard-driven prompt (`Questionary` / `Rich`):
* *"We detected Playwright E2E tests alongside unit tests. Run E2E tests in a separate parallel job? [Y/n]"*
* Includes a `--yes` / `--non-interactive` flag for headless automation where sensible defaults are chosen automatically.

### 4.3. Interactive Visual Diff & Dry-Run (`--dry-run` / `--diff`)
Before modifying any existing YAML file, the user can preview changes via a colorized, side-by-side or unified diff right in the terminal. If a file already exists, the CLI prompts:
* `[A]pply changes  [D]iff preview  [S]kip file  [B]ackup & overwrite`

### 4.4. Non-Destructive "Smart Merge" (Preserving User Customizations)
The #1 reason developers abandon YAML generators is that re-running the tool wipes out their custom steps (like Slack notifications or custom deployment secrets). We solve this via two mechanisms:
1. **AST Round-Trip Merging (`ruamel.yaml`):** We parse the existing YAML file into an Abstract Syntax Tree, preserving all user comments, custom jobs, and formatting, and only update the specific keys managed by our tool.
2. **Protected Comment Directives:** Users can mark any custom step with `# @autoyaml:ignore` or `# @autoyaml:preserve`, and the engine guarantees that block will never be modified or deleted during regeneration.

### 4.5. Continuous Drift Detection (`autoyaml check` & Pre-Commit Hook)
Codebases evolve. A developer might add `redis` to `requirements.txt` or add a new microservice directory, forgetting to update `.github/workflows/ci.yml`.
* Running `autoyaml check` compares the current codebase fingerprint against the existing YAML files.
* If drift is detected, it outputs a warning: *"⚠️ Drift Detected: `redis` was added to `pyproject.toml`, but `.github/workflows/ci.yml` is missing a Redis service container. Run `autoyaml sync` to update."*
* Can be installed as a lightweight Git pre-commit hook or a 2-second CI check.

### 4.6. Zero-Config by Default, `.autoyaml.toml` for Power Users
Works out of the box with zero configuration files. If a team wants persistent overrides (e.g., always use `ubuntu-24.04-arm`, or enforce a custom internal Docker registry), they can run `autoyaml init` to save a minimal `.autoyaml.toml` policy file.

---

## 5. System Architecture & Data Pipeline

The architecture enforces a strict unidirectional data flow across five decoupled layers:

```text
[ 1. Fast File Indexer ] 
          │  (Gitignore-aware file tree & file contents cache)
          ▼
[ 2. Provider & Parser Engine ] 
          │  (Python, Node, Rust, Go, C++, Docker, Compose parsers)
          ▼
[ 3. Project Context Graph (IR) ] 
          │  (Strongly-typed Pydantic Intermediate Representation)
          ▼
[ 4. Rule Engine & Jinja2/AST Synthesizer ] 
          │  (Maps IR -> Target YAML AST + Smart Merge with existing files)
          ▼
[ 5. Schema Validator & Formatter ] 
             (Validates against JSON Schemas -> Writes via ruamel.yaml)
```

### The Intermediate Representation (Project Context Schema)
All scanners and parsers output into a strict, strongly-typed `ProjectContext` model (built with `Pydantic`). Generators **never** read the filesystem directly; they only read `ProjectContext`.

```python
from pydantic import BaseModel
from typing import List, Optional, Dict

class ServiceRequirement(BaseModel):
    name: str                  # e.g., "postgres", "redis"
    image: str                 # e.g., "postgres:16-alpine"
    ports: List[int]           # e.g., [5432]
    env: Dict[str, str]        # e.g., {"POSTGRES_PASSWORD": "test"}
    source_file: str           # For --explain output (e.g., "docker-compose.yml")

class LanguageContext(BaseModel):
    language: str              # e.g., "python", "node", "cpp", "go"
    runtime_version: str       # e.g., "3.12", "20.x"
    version_source: str        # e.g., ".python-version"
    package_manager: str       # e.g., "uv", "poetry", "pnpm", "cmake"
    install_cmd: str           # e.g., "uv sync --frozen"
    build_cmd: Optional[str]   # e.g., "pnpm run build"
    test_cmd: Optional[str]    # e.g., "pytest --cov"
    lint_cmd: Optional[str]    # e.g., "ruff check ."
    working_dir: str = "."     # Supports monorepo sub-packages

class ContainerContext(BaseModel):
    dockerfile_path: str
    exposed_ports: List[int]
    base_image: str
    has_healthcheck: bool

class ProjectContext(BaseModel):
    repo_name: str
    is_monorepo: bool
    languages: List[LanguageContext]
    services: List[ServiceRequirement]
    containers: List[ContainerContext]
    required_secrets: List[str]
    explain_log: List[str]     # Audit trail of every heuristic triggered
```

---

## 6. Recommended Tech Stack & Package Structure

### Core Dependencies
* **Language:** Python 3.10+
* **CLI & TUI:** `typer` (CLI routing), `rich` (tables, trees, syntax-highlighted diffs, spinners), `questionary` (interactive prompts).
* **Data Modeling & Validation:** `pydantic` (Intermediate Representation & config validation), `jsonschema` (validating generated GitHub Actions / K8s YAML against official schemas).
* **File Traversal:** `pathspec` (fast `.gitignore`-compliant file tree walking).
* **Config Parsers:** `tomli` / `tomli-w` (TOML), `dockerfile-parse` or custom lexer (Dockerfiles), `packaging` (version specifier parsing).
* **YAML & Templating:** `jinja2` (structural composition) + `ruamel.yaml` (comment-preserving AST manipulation and round-trip smart merging).

### Modular Directory Layout
```text
autoyaml/
├── pyproject.toml
├── src/
│   └── autoyaml/
│       ├── cli.py                  # Typer entrypoints (generate, diff, check, init)
│       ├── ui/
│       │   ├── console.py          # Rich explain-tree & spinner rendering
│       │   ├── differ.py           # Side-by-side & unified terminal diff viewer
│       │   └── prompts.py          # Interactive ambiguity resolution
│       ├── core/
│       │   ├── indexer.py          # Gitignore-aware fast repository scanner
│       │   ├── context.py          # Pydantic ProjectContext models (IR)
│       │   ├── merger.py           # ruamel.yaml AST smart-merge & comment preservation
│       │   └── validator.py        # Pre-flight JSON schema & syntax verification
│       ├── detectors/              # Modular language/stack providers
│       │   ├── base.py             # Abstract Detector interface
│       │   ├── python_detector.py  # Parses pyproject.toml, requirements.txt, uv, poetry
│       │   ├── node_detector.py    # Parses package.json, workspaces, lockfiles
│       │   ├── cpp_detector.py     # Parses CMakeLists.txt, Makefile, Conan/vcpkg
│       │   ├── docker_detector.py  # Parses Dockerfile & docker-compose.yml
│       │   └── env_detector.py     # Parses .env.example & secret references
│       ├── synthesizers/           # Target YAML generators
│       │   ├── github_actions.py   # CI, CD, Matrix, Service containers
│       │   ├── kubernetes.py       # Deployment, Service, HPA, Ingress
│       │   └── maintenance.py      # Dependabot, Release-Please, Stale bot
│       ├── templates/              # Composable Jinja2 macros & base templates
│       └── schemas/                # Bundled JSON schemas for offline validation
└── tests/
    ├── fixtures/                   # Sample polyglot & monorepo directory trees
    └── test_heuristics.py          # Snapshot tests ensuring 100% determinism
```

---

## 7. Phased Execution Roadmap

### Phase 1: Core Engine, Indexer & IR Foundation (Weeks 1–2)
* Set up `pyproject.toml`, `typer` CLI skeleton, and `Rich` console logging.
* Build the `RepoIndexer` using `pathspec` so the scanner reads relevant config files in $<50\text{ ms}$ while ignoring `node_modules`, `.git`, and virtual environments.
* Define the `ProjectContext` Pydantic models and the abstract `BaseDetector` plugin class.

### Phase 2: Deep Heuristic Detectors (Weeks 3–4)
* Implement `PythonDetector`, `NodeDetector`, `CppDetector`, and `DockerDetector`.
* Build the **Service Inference Engine** that correlates `docker-compose.yml` and library dependencies (`redis`, `psycopg2`, `prisma`) into `ServiceRequirement` objects.
* Build the **Explainability Recorder** so every detector logs *why* it made a decision (`"Detected pytest via pyproject.toml line 24"`).

### Phase 3: Template Synthesis & AST Smart Merger (Weeks 5–6)
* Create modular Jinja2 templates for **GitHub Actions CI**, **Testing**, **Maintenance (Dependabot)**, and **Kubernetes**.
* Build the `SmartMerger` using `ruamel.yaml` so re-running the generator updates managed jobs while preserving user comments and `# @autoyaml:preserve` blocks.
* Integrate offline JSON Schema validation (`github-workflow.json`, Kubernetes OpenAPI schemas) to guarantee zero invalid YAML output.

### Phase 4: Polish, UX Features & Drift Detection (Weeks 7–8)
* Implement `--dry-run` and `--diff` with syntax-highlighted terminal diffs.
* Add interactive ambiguity prompts via `questionary` (with `--yes` fallback).
* Implement `autoyaml check` for CI/pre-commit drift detection and write snapshot tests across 15+ real-world repository fixtures.