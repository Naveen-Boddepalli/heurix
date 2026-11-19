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

export const HX_VERSION = '0.3.0';
export const REPO_URL = 'https://github.com/Naveen-Boddepalli/heurix';

export const INSTALL_METHODS = [
  {
    id: 'pipx',
    label: 'pipx',
    command: 'pipx install heurix',
    note: 'Recommended. Installs hx in its own environment. Needs Python 3.10 or newer.',
  },
  {
    id: 'pip',
    label: 'pip',
    command: 'pip install heurix',
    note: 'Installs into whatever environment is active.',
  },
  {
    id: 'curl',
    label: 'Shell script',
    command: 'curl -fsSL https://raw.githubusercontent.com/Naveen-Boddepalli/heurix/main/install.sh | bash',
    note: 'Sets up a dedicated environment and puts hx on your PATH. Read the script before piping it to bash.',
  },
  {
    id: 'docker',
    label: 'Docker',
    command: 'docker run --rm -v "$(pwd):/workspace" ghcr.io/naveen-boddepalli/heurix:latest generate --dry-run',
    note: 'No local Python needed. Images are built for linux/amd64 and linux/arm64.',
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
    title: 'Runtime versions',
    detector: 'Language Detectors',
    summary: 'Reads the version you pinned instead of assuming a default.',
    signals: ['.python-version', '.nvmrc', 'rust-toolchain.toml', 'go.mod', 'CMakeLists.txt'],
    output: 'Version passed to setup-python, setup-node, rust-toolchain, setup-go',
  },
  {
    id: 'lockfiles',
    title: 'Package managers',
    detector: 'Python & Node',
    summary: 'Picks the install command, frozen-lockfile flags, and cache setup for the package manager you use.',
    signals: ['uv.lock', 'poetry.lock', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lockb'],
    output: 'astral-sh/setup-uv, pnpm/action-setup, Swatinem/rust-cache',
  },
  {
    id: 'services',
    title: 'Databases and caches',
    detector: 'Deps & Compose',
    summary: 'Adds Postgres, Redis, or MongoDB service containers when your dependencies or docker-compose.yml use them. Duplicates are merged into one.',
    signals: ['psycopg / psycopg2 / asyncpg', 'prisma / pg', 'redis / ioredis', 'docker-compose.yml'],
    output: 'One CI service per backend with credentials, ports, and health checks',
  },
  {
    id: 'secrets',
    title: 'Env vars and secrets',
    detector: 'EnvDetector',
    summary: 'Splits .env.example into plain defaults and secrets. Deploy tokens are only given to deploy jobs.',
    signals: ['.env.example', '.env.template', 'SECRET / TOKEN / KEY / URL / DSN'],
    output: 'env: defaults, ${{ secrets.* }}, k8s/secret.yaml without VERCEL_* / FIREBASE_*',
  },
  {
    id: 'monorepo',
    title: 'Monorepos',
    detector: 'NodeDetector',
    summary: 'Finds workspace packages and gives each one its own job, path filter, and Dependabot entry.',
    signals: ['pnpm-workspace.yaml', 'turbo.json', 'nx.json', 'Cargo workspaces'],
    output: 'Per-package jobs, path triggers, and dependabot.yml entries',
  },
  {
    id: 'containers',
    title: 'Containers and Kubernetes',
    detector: 'Docker + Kubernetes',
    summary: 'Reads ports and health checks from your Dockerfile. Manifests are only generated if there is one, and run as non-root with a read-only filesystem.',
    signals: ['Dockerfile FROM/EXPOSE', 'HEALTHCHECK', 'FastAPI / Next.js / Streamlit'],
    output: 'k8s/deployment, service, ingress, configmap, secret, kind-config',
  },
  {
    id: 'cloud',
    title: 'Vercel and Firebase',
    detector: 'CloudDetector',
    summary: 'Adds a deploy job that runs after tests pass on main.',
    signals: ['vercel.json', '.vercel', 'firebase.json', '.firebaserc'],
    output: 'deploy_vercel / deploy_firebase jobs gated by needs: test',
  },
  {
    id: 'maintenance',
    title: 'Dependabot',
    detector: 'MaintenanceSynthesizer',
    summary: 'Weekly update checks for every package ecosystem found, plus GitHub Actions and Docker.',
    signals: ['github-actions', 'pip', 'npm', 'cargo', 'gomod', 'docker'],
    output: '.github/dependabot.yml covering root and monorepo sub-dirs',
  },
];

export const CLI_COMMANDS = [
  {
    cmd: 'hx generate',
    title: 'Write the files',
    desc: 'Prints what it found, validates the output, and merges it into any existing files. If it is about to overwrite something you edited, it says so first.',
    snippet: `$ hx generate
Codebase Scan: billing-api
├── Detected Python 3.12 (via .python-version)
├── Detected Package Manager: uv (via uv.lock)
├── Detected Framework: FastAPI
├── Inferred Backing Service: PostgreSQL 16 (via python dependencies)
├── Parsed Dockerfile 'Dockerfile': exposed=[8000], healthcheck=True
└── Loaded configuration policy from .heurix.toml

.github/workflows/ci.yml: these existing values will be replaced:
  - jobs.test.steps['Run tests (python)'].run: 'pytest -q' -> 'uv run python -m pytest'
  To keep your version, add '# @heurix:preserve' to the end of that key's line (or on the line above a step).

Written: .github/workflows/ci.yml
Written: k8s/deployment.yaml  (+6 more)
Successfully synthesized 8 file(s)!`,
  },
  {
    cmd: 'hx diff',
    title: 'Preview the changes',
    desc: 'Same as generate --dry-run --diff --yes. Shows a diff against what is on disk and writes nothing.',
    snippet: `$ hx diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -6,9 +6,13 @@
   test:
     runs-on: self-hosted # @heurix:preserve
     steps:
-      - uses: actions/checkout@v4
-      - name: Set up Python 3.11
-        uses: actions/setup-python@v5
+      - name: Checkout repository
+        uses: actions/checkout@v7
+      - name: Install uv
+        uses: astral-sh/setup-uv@v5
+      - name: Set up Python 3.12
+        uses: actions/setup-python@v7.1.0
       # @heurix:preserve
       - name: Upload coverage to internal bucket`,
  },
  {
    cmd: 'hx check',
    title: 'Check for drift',
    desc: 'Exits 1 if the workflow no longer matches the repo: a missing service, an old runtime version, two services on one port, or a broken .heurix.toml. Useful in CI and as a pre-commit hook.',
    snippet: `$ hx check
Drift Detected (2 issue(s)):

[ERROR] .github/workflows/ci.yml: Job 'test': services 'postgres', 'db' all bind host port 5432; only one can start, so the job will fail.
  Recommendation: Run 'hx generate' to merge duplicate services, or remove the extra service.

[WARNING] .github/workflows/ci.yml: Service 'redis' is required by codebase dependencies (python dependencies) but missing from workflow.
  Recommendation: Run 'hx generate' to inject service 'redis'.`,
  },
  {
    cmd: 'hx scan',
    title: 'See what was detected',
    desc: 'Prints the detected project as JSON. Handy for debugging or for feeding other scripts.',
    snippet: `$ hx scan
{
  "repo_name": "billing-api",
  "languages": [
    {
      "language": "python",
      "runtime_version": "3.12",
      "package_manager": "uv",
      "install_cmd": "uv sync --frozen --all-extras",
      "test_cmd": "uv run python -m pytest",
      "framework": "FastAPI"
    }
  ],
  "services": [{ "name": "postgres", "image": "postgres:16-alpine", "ports": [5432] }],
  "confidence": 0.98
}`,
  },
  {
    cmd: 'hx init',
    title: 'Add a config file',
    desc: 'Writes a commented .heurix.toml. include_k8s is set based on whether you already have k8s/deployment.yaml.',
    snippet: `$ hx init
Created .heurix.toml

$ cat .heurix.toml
[engine]
runner = "ubuntu-latest"
non_destructive = true

[ci]
include_dependabot = true
include_k8s = false  # also controls whether \`hx check\` verifies k8s/ manifests
# paths_ignore = ["docs/**", "**/*.md"]  # skip CI when only these files change`,
  },
];

export interface PolicyKey {
  key: string;
  section: string;
  example: string;
  desc: string;
  isNew?: boolean;
}

export const POLICY_KEYS: PolicyKey[] = [
  { section: '[engine]', key: 'runner', example: '"ubuntu-24.04-arm"', desc: 'Default runs-on for generated jobs.' },
  { section: '[engine]', key: 'non_destructive', example: 'true', desc: 'Smart-merge into existing files instead of overwriting.' },
  { section: '[ci]', key: 'paths_ignore', example: '["docs/**", "**/*.md"]', desc: 'Skip CI on push / pull_request when only matching files change.', isNew: true },
  { section: '[ci]', key: 'paths', example: '["src/**", "tests/**"]', desc: 'Run CI only for these files. Replaces the inferred monorepo filter; ignores fold in as !pattern.', isNew: true },
  { section: '[ci]', key: 'include_k8s', example: 'false', desc: 'Generate (and have hx check verify) k8s/ manifests.' },
  { section: '[ci]', key: 'include_dependabot', example: 'true', desc: 'Generate .github/dependabot.yml.' },
  { section: '[ci]', key: 'action_shas', example: '{ "actions/checkout" = "<sha>" }', desc: 'Pin actions to 40-char commit SHAs.' },
  { section: '[ci.env]', key: 'DATABASE_URL', example: '"postgresql://..."', desc: 'Override service connection URLs (DATABASE_URL, REDIS_URL, MONGO_URL, MONGODB_URI).' },
  { section: '[secrets]', key: 'deploy', example: '["NETLIFY_TOKEN"]', desc: 'Treat extra keys as deploy-only: never in test env or k8s/secret.yaml.' },
  { section: '[kubernetes]', key: 'image_tag', example: '"1.4.2"', desc: 'Image tag for the Deployment (falls back to IMAGE_TAG / APP_VERSION, then latest).' },
  { section: '[overrides]', key: 'python / node / go', example: '"3.12"', desc: 'Pin a runtime version explicitly.' },
];

export const POLICY_EXAMPLE = `# .heurix.toml
[engine]
runner = "ubuntu-latest"

[ci]
include_k8s = true
# Skip CI when only docs change
paths_ignore = ["docs/**", "**/*.md"]

[ci.action_shas]
"actions/checkout" = "<40-char-commit-sha>"

[kubernetes]
image_tag = "1.4.2"

[overrides]
python = "3.12"`;

export interface ReleaseNote {
  version: string;
  date: string;
  headline: string;
  groups: { label: string; tone: 'added' | 'fixed' | 'changed' | 'security'; items: string[] }[];
}

export const RELEASES: ReleaseNote[] = [
  {
    version: '0.3.0',
    date: '2026-11-17',
    headline: 'CI trigger path filters',
    groups: [
      {
        label: 'Added',
        tone: 'added',
        items: [
          '[ci].paths sets which files trigger CI and replaces the inferred monorepo filter.',
          '[ci].paths_ignore skips CI when only matching files change, e.g. ["docs/**", "**/*.md"].',
          'With both set, ignores fold into paths as !pattern entries, since GitHub rejects paths + paths-ignore together.',
          'Regenerating updates the filters in an existing ci.yml whenever either key is set.',
        ],
      },
    ],
  },
  {
    version: '0.2.2',
    date: '2026-11-16',
    headline: 'Generated CI that always starts, plus safer merges',
    groups: [
      {
        label: 'Fixed',
        tone: 'fixed',
        items: [
          'Duplicate backing services from dependencies and docker-compose merge into one container, keeping your compose image.',
          'Compose-only Postgres gets credentials, and DATABASE_URL always matches the service.',
          'Compose services without ports: publish their standard port (5432, 6379, 27017).',
          'Flat-layout Python projects run tests as python -m pytest.',
          'Monorepo path filters include root files and .github/workflows/**; Cargo workspaces cache ./target.',
        ],
      },
      {
        label: 'Security',
        tone: 'security',
        items: ['Deploy credentials (VERCEL_*, FIREBASE_*, [secrets].deploy) are no longer written to k8s/secret.yaml.'],
      },
      {
        label: 'Added',
        tone: 'added',
        items: [
          'Replacement notices: hx generate lists every hand-edited value it would replace.',
          'Key-level preserve: end a runs-on, services, needs, or strategy line with # @heurix:preserve.',
          'hx check reports services in one job that bind the same host port.',
          'An invalid .heurix.toml fails hx check with an "Invalid Policy" error.',
        ],
      },
      {
        label: 'Changed',
        tone: 'changed',
        items: [
          'Kubernetes manifests are generated only for containerized repos (or an explicit [kubernetes] policy).',
          'hx init sets include_k8s from whether k8s/deployment.yaml exists.',
          'Default actions: checkout@v7, setup-python@v7.1.0, setup-node@v7, setup-go@v7.',
        ],
      },
    ],
  },
  {
    version: '0.2.0',
    date: '2026-11-14',
    headline: 'Monorepos, templates, and policy',
    groups: [
      {
        label: 'Added',
        tone: 'added',
        items: [
          'Monorepo topology and multi-job CI.',
          'Jinja2 templates, .heurix.toml policy, interactive prompts, diff viewer, and pre-commit hook.',
        ],
      },
    ],
  },
];
