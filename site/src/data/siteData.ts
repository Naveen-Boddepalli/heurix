import generatedDocs from './generatedDocs.json';

export interface DocEntry {
  id: string;
  title: string;
  file: string;
  group: string;
  markdown: string;
}

export const SITE_DOCS: {
  llmsTxt: string;
  llmsFullBytes: number;
  llmsFullLines: number;
  docs: DocEntry[];
} = generatedDocs;

export const INSTALL_METHODS = [
  {
    id: 'pipx',
    label: 'pipx (Recommended)',
    command: 'pipx install heurix',
    note: 'Installs hx globally in an isolated Python >= 3.10 environment.',
  },
  {
    id: 'pip',
    label: 'pip',
    command: 'pip install heurix',
    note: 'Standard PyPI package installation into your active virtual environment.',
  },
  {
    id: 'curl',
    label: 'Shell script',
    command: 'curl -fsSL https://raw.githubusercontent.com/Naveen-Boddepalli/heurix/main/install.sh | bash',
    note: 'One-line installer that sets up a dedicated environment and exposes hx.',
  },
  {
    id: 'docker',
    label: 'Docker',
    command: 'docker run --rm -v "$(pwd):/workspace" ghcr.io/naveen-boddepalli/heurix:latest generate --dry-run',
    note: 'Zero Python dependency — runs multi-arch linux/amd64 and linux/arm64 images.',
  },
];

export interface HeuristicCardData {
  id: string;
  title: string;
  detector: string;
  summary: string;
  signals: string[];
  output: string;
}

export const HEURISTIC_CARDS: HeuristicCardData[] = [
  {
    id: 'versions',
    title: 'Exact Version Pinning',
    detector: 'Language Detectors',
    summary: 'Reads runtime pins directly from repository files rather than falling back to stale defaults.',
    signals: ['.python-version', '.nvmrc', 'rust-toolchain.toml', 'go.mod', 'CMakeLists.txt'],
    output: 'Pins actions/setup-python, setup-node, rust-toolchain, setup-go',
  },
  {
    id: 'lockfiles',
    title: 'Lockfile & Cache Fingerprinting',
    detector: 'Python & Node',
    summary: 'Selects frozen install flags and native CI caching actions tailored to the exact package manager.',
    signals: ['uv.lock', 'poetry.lock', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lockb'],
    output: 'astral-sh/setup-uv, pnpm/action-setup, Swatinem/rust-cache',
  },
  {
    id: 'services',
    title: 'Service Auto-Provisioning',
    detector: 'Deps & Compose',
    summary: 'Infers Postgres, Redis, and MongoDB requirements from client libraries or docker-compose services.',
    signals: ['psycopg2 / asyncpg', 'prisma / pg', 'redis / ioredis', 'docker-compose.yml'],
    output: 'CI services: containers with pg_isready / redis-cli health checks',
  },
  {
    id: 'secrets',
    title: 'Env & Secret Wiring',
    detector: 'EnvDetector',
    summary: 'Separates safe defaults from sensitive keys in env templates using deterministic keyword heuristics.',
    signals: ['.env.example', '.env.template', 'SECRET / TOKEN / KEY / AUTH'],
    output: 'Non-sensitive env: blocks + ${{ secrets.* }} & K8s secretRef',
  },
  {
    id: 'monorepo',
    title: 'Monorepo Topology',
    detector: 'NodeDetector',
    summary: 'Detects workspace managers and enumerates sub-packages for targeted CI path triggers and Dependabot.',
    signals: ['pnpm-workspace.yaml', 'turbo.json', 'nx.json', 'workspaces'],
    output: 'Path-filtered triggers & per-package dependabot.yml entries',
  },
  {
    id: 'containers',
    title: 'Container & K8s Sync',
    detector: 'Docker + Kubernetes',
    summary: 'Parses multi-stage Dockerfiles for ports, health checks, and runtime baselines to size K8s probes.',
    signals: ['Dockerfile FROM/EXPOSE', 'HEALTHCHECK', 'FastAPI / Next.js / Streamlit'],
    output: 'k8s/deployment.yaml, service.yaml, ingress.yaml, kind-config.yaml',
  },
  {
    id: 'cloud',
    title: 'Cloud Deployment Targets',
    detector: 'CloudDetector',
    summary: 'Identifies Vercel and Firebase project configs and generates gated production deploy jobs.',
    signals: ['vercel.json', '.vercel', 'firebase.json', '.firebaserc'],
    output: 'deploy_vercel / deploy_firebase jobs gated by needs: test',
  },
  {
    id: 'maintenance',
    title: 'Ecosystem Hygiene',
    detector: 'MaintenanceSynthesizer',
    summary: 'Synthesizes weekly Dependabot update schedules across every package ecosystem and container detected.',
    signals: ['github-actions', 'pip', 'npm', 'cargo', 'gomod', 'docker'],
    output: '.github/dependabot.yml covering root and monorepo sub-dirs',
  },
];

export const CLI_COMMANDS = [
  {
    cmd: 'hx generate --dry-run',
    title: 'Scan & preview with explainability',
    desc: 'Runs all 8 detectors in <50ms, renders the Rich heuristic reasoning tree, and validates outputs against JSON schemas without touching disk.',
    snippet: `$ hx generate --dry-run
🔍 Codebase Scan: billing-api
├── ✔ Detected Python 3.12 (via .python-version)
├── ✔ Detected Package Manager: uv (via uv.lock)
├── ✔ Detected Framework: FastAPI
├── ✔ Inferred Backing Service: PostgreSQL 16 (via python dependencies)
└── ✔ Parsed Dockerfile 'Dockerfile': exposed=[8000], healthcheck=True

Dry run completed. 5 files validated (0 schema errors).`,
  },
  {
    cmd: 'hx diff',
    title: 'Non-destructive AST diff preview',
    desc: 'Compares existing YAML files against merged output using ruamel.yaml round-trip AST merging while preserving # @heurix:preserve blocks.',
    snippet: `$ hx diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -11,5 +11,7 @@
-      - name: Set up Python 3.11
-        uses: actions/setup-python@v5
-        with:
-          python-version: '3.11'
+      - name: Install uv
+        uses: astral-sh/setup-uv@v5
+      - name: Set up Python 3.12
+        with:
+          python-version: '3.12'
       # @heurix:preserve
       - name: Upload coverage to internal bucket`,
  },
  {
    cmd: 'hx check',
    title: 'Continuous CI/CD drift detection',
    desc: 'Verifies existing workflows match current dependencies and runtime pins. Exits 1 on drift—ideal for Git pre-commit hooks and CI checks.',
    snippet: `$ hx check
⚠️ Drift Detected (2 issue(s)):

.github/workflows/ci.yml: Service 'redis' is required by codebase dependencies (python dependencies) but missing from workflow.
  ↳ Recommendation: Run 'hx generate' to inject service 'redis'.

.github/workflows/ci.yml: Runtime version mismatch: codebase specifies python 3.12 (.python-version), not found in workflow.
  ↳ Recommendation: Run 'hx generate' to update python version.`,
  },
  {
    cmd: 'hx scan',
    title: 'Inspect ProjectContext IR JSON',
    desc: 'Exports the strongly-typed Pydantic Intermediate Representation extracted by detectors for inspection or custom tooling pipelines.',
    snippet: `$ hx scan
{
  "repo_name": "billing-api",
  "languages": [
    {
      "language": "python",
      "runtime_version": "3.12",
      "package_manager": "uv",
      "install_cmd": "uv sync --frozen",
      "framework": "FastAPI"
    }
  ],
  "services": [{ "name": "postgres", "image": "postgres:16-alpine", "ports": [5432] }],
  "confidence": 0.98
}`,
  },
];
