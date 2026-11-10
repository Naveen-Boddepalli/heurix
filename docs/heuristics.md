# Deep Heuristics Matrix

Heurix uses eight modular, deterministic detectors (`BaseDetector` subclasses) that read the `.gitignore`-aware in-memory file index (`RepoIndexer`) and populate a shared `ProjectContext` Intermediate Representation (IR).

## 1. Python (`PythonDetector`)

- **Trigger signals:** `pyproject.toml`, `requirements.txt`, `Pipfile`, `setup.py`, `setup.cfg`, `.python-version`, `uv.lock`, `poetry.lock`, or `*.py` files.
- **Version pinning:** Checks `.python-version`, `.tool-versions`, and `pyproject.toml` (`project.requires-python` or `tool.poetry.dependencies.python`). Defaults to `3.12`.
- **Package managers & lockfiles:**
  - `uv.lock` → `uv sync --frozen` (uses `astral-sh/setup-uv@v5` with cache enabled)
  - `poetry.lock` → `poetry install --no-interaction` (uses `snok/install-poetry@v1`)
  - `Pipfile` / `Pipfile.lock` → `pipenv install --deploy`
  - `requirements.txt` (+ `requirements-dev.txt`) → `pip install -r requirements.txt`
  - `pyproject.toml` → `pip install -e '.[dev]'` / `'.[test]'` / `'.'`
- **Frameworks:** `FastAPI`, `Streamlit`, `Django`, `Flask`.
- **Tests & linters:** `pytest`, `python manage.py test`, `python -m unittest discover`; `ruff check .`, `flake8 .`. Automatically prefixes commands with `uv run` or `poetry run` when using isolated lockfiles.
- **Backing services inferred:** `psycopg2` / `asyncpg` / `postgresql` / `pgvector` → `postgres:16-alpine` (port 5432); `redis` / `aioredis` / `celery` → `redis:7-alpine` (port 6379).

## 2. Node.js / TypeScript (`NodeDetector`)

- **Trigger signals:** `package.json`, `.nvmrc`, `.node-version`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`.
- **Version pinning:** Checks `.nvmrc`, `.node-version`, and `package.json` `engines.node`. Defaults to `20.x`.
- **Package managers:**
  - `pnpm-lock.yaml` → `pnpm i --frozen-lockfile` (`pnpm/action-setup@v4` + `cache: 'pnpm'`)
  - `yarn.lock` → `yarn install --frozen-lockfile` (`cache: 'yarn'`)
  - `bun.lockb` / `bun.lock` → `bun install --frozen-lockfile` (`oven-sh/setup-bun@v2`)
  - `package-lock.json` → `npm ci` (`cache: 'npm'`)
- **Monorepo topology:** Detects `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, or `package.json` `workspaces`, enumerating sub-packages and adding path triggers & Dependabot directories.
- **Frameworks, test runners & services:** `Next.js`, `Express`, `NestJS`, `Vite`, `Nuxt`; `vitest`, `jest`, `playwright`; infers `postgres` (from `pg`, `prisma`, `typeorm`), `redis` (from `ioredis`, `redis`, `bullmq`), and `mongodb` (from `mongoose`, `mongodb`).

## 3. Rust (`RustDetector`)

- **Trigger signals:** `Cargo.toml`, `rust-toolchain.toml`.
- **Version pinning:** Extracts `toolchain.channel` from `rust-toolchain.toml` or `rust-toolchain` (defaults to `stable`).
- **Frameworks:** `Actix-Web`, `Axum`, `Rocket`.
- **Synthesized commands:** `cargo fetch`, `cargo clippy -- -D warnings`, `cargo build --release`, `cargo test --verbose` paired with `dtolnay/rust-toolchain@stable` and `Swatinem/rust-cache@v2`.

## 4. Go (`GoDetector`)

- **Trigger signals:** `go.mod` or `*.go` files.
- **Version pinning:** Parses the `go <version>` directive from `go.mod` (defaults to `1.22`).
- **Frameworks:** `Gin`, `Echo`, `Fiber`.
- **Synthesized commands:** `go mod download`, `golangci-lint run`, `go build -v ./...`, `go test -v -race -cover ./...` paired with `actions/setup-go@v5`.

## 5. C / C++ (`CppDetector`)

- **Trigger signals:** `CMakeLists.txt`, `conanfile.txt`, `conanfile.py`, `vcpkg.json`, or `*.cpp`/`*.cc`/`*.hpp`/`*.c`/`*.h` files.
- **Version & build tools:** Detects `CMAKE_CXX_STANDARD` (`c++17`, `c++20`, etc.) from `CMakeLists.txt`, `Conan`, `vcpkg`, `CMake` (exporting `compile_commands.json`), or `Make`.
- **Linters & tests:** `.clang-tidy` → `clang-tidy -p build` (installed via `apt` and sequenced after build so `compile_commands.json` exists), and `ctest --test-dir build --output-on-failure`.

## 6. Docker & Compose (`DockerDetector`)

- **Dockerfile parsing:** Extracts final-stage `FROM <base_image> [AS <target>]`, `EXPOSE <ports>`, and `HEALTHCHECK` presence.
- **Compose parsing:** Scans `docker-compose.yml`, `docker-compose.yaml`, `compose.yml`, and `compose.yaml` services (`postgres`, `redis`, `mongo`, etc.) to populate CI `services:` blocks with matching images, environment variables, and ports.

## 7. Environment & Secrets (`EnvDetector`)

- **Trigger signals:** `.env.example`, `.env.template`, `.env.sample`, `.env.dist`, `.env.local.example`.
- **Classification:** Variable keys containing `SECRET`, `PASSWORD`, `TOKEN`, `KEY`, `AUTH`, `PRIVATE`, `CREDENTIAL`, or `CERT` are wired to `${{ secrets.<KEY> }}` and referenced in Kubernetes `secretRef`. Non-sensitive defaults are populated into `env:` and Kubernetes `configMapRef`.

## 8. Cloud Deployment Targets (`CloudDetector`)

- **Vercel:** Detects `vercel.json` or `.vercel`, extracts project metadata and serverless `api/` presence, adds `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` secrets, and synthesizes a `deploy_vercel` job using `amondnet/vercel-action@v25` on pushes to `main`.
- **Firebase:** Detects `firebase.json` or `.firebaserc`, extracts `projectId` and active features (`hosting`, `functions`, `firestore`, `storage`, `emulators`, `remoteconfig`), adds `FIREBASE_SERVICE_ACCOUNT`, and synthesizes `deploy_firebase` via `FirebaseExtended/action-hosting-deploy@v0`.
