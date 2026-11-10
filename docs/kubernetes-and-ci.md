# Synthesized CI/CD & Kubernetes Manifests

From a single `ProjectContext` Intermediate Representation, Heurix synthesizes three families of configuration files, validating every byte against JSON schemas (`PreflightValidator`) prior to writing to disk.

## 1. GitHub Actions (`.github/workflows/ci.yml`)

- Pins exact runtime setup actions (`actions/setup-python@v5`, `astral-sh/setup-uv@v5`, `actions/setup-node@v4`, `pnpm/action-setup@v4`, `oven-sh/setup-bun@v2`, `dtolnay/rust-toolchain@stable`, `actions/setup-go@v5`).
- Enables package manager caching (`cache: 'pnpm'`, `Swatinem/rust-cache@v2`, `enable-cache: true`).
- Injects `services:` containers (`postgres:16-alpine`, `redis:7-alpine`, etc.) with Docker health checks (`pg_isready`, `redis-cli ping`) and ports.
- Wires non-sensitive defaults from `.env.example` into `env:` and sensitive variables into `${{ secrets.KEY }}`.
- Adds `deploy_vercel` or `deploy_firebase` jobs (with `needs: test`) when cloud targets (`vercel.json`, `firebase.json`, `.firebaserc`) are present.

## 2. Dependabot (`.github/dependabot.yml`)

Generates weekly update schedules for `github-actions` plus every ecosystem detected in the repository (`pip`, `npm`, `cargo`, `gomod`, `docker`), including sub-directory rules for monorepo packages.

## 3. Kubernetes Manifests (`k8s/`)

When a `Dockerfile` or supported web framework (`FastAPI`, `Streamlit`, `Next.js`, `Express`) is detected (and `--k8s` is enabled), Heurix synthesizes:

- `k8s/deployment.yaml`: Container image, port inferred from `Dockerfile EXPOSE` or framework defaults (`8000` FastAPI, `3000` Next.js/Express, `8501` Streamlit, `8080` fallback), runtime-appropriate CPU/memory requests (`50m`/`64Mi` for Go/Rust vs. `100m`/`256Mi` for Python/Node), `livenessProbe`, `readinessProbe` (`/_stcore/health` for Streamlit), and `envFrom` (`configMapRef` / `secretRef`).
- `k8s/service.yaml`: `ClusterIP` service targeting the container port.
- `k8s/ingress.yaml`: `networking.k8s.io/v1` Ingress with `ingressClassName: nginx`.
- `k8s/kind-config.yaml`: Local Kubernetes in Docker cluster configuration with port mappings.
- `k8s/configmap.yaml`: Synthesized whenever non-sensitive environment defaults are extracted from `.env.example` / `.env.template`.
