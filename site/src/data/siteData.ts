export const HX_VERSION = '0.4.0';
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
+        uses: astral-sh/setup-uv@v10.4.0
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
⚠️ Drift Detected (2 issue(s)):

.github/workflows/ci.yml: Job 'test': services 'postgres', 'db' all bind host port 5432; only one can start, so the job will fail.
  ↳ Recommendation: Run 'hx generate' to merge duplicate services, or remove the extra service.

.github/workflows/ci.yml: Service 'redis' is required by codebase dependencies (python dependencies) but missing from workflow.
  ↳ Recommendation: Run 'hx generate' to inject service 'redis'.`,
  },
  {
    cmd: 'hx check --security',
    title: 'Audit workflow security',
    desc: 'Also checks every workflow for write-all permissions, template injection, unpinned third-party actions, risky pull_request_target / workflow_run checkouts, and checkout tokens left in .git/config. Rule IDs match zizmor; add --format sarif to upload to GitHub code scanning.',
    snippet: `$ hx check --security
🔒 Security Findings (3 issue(s)):

.github/workflows/ci.yml:38: jobs.test.steps[1] (Install uv) uses astral-sh/setup-uv@v10.4.0, a tag or branch its owner can move to different code. [unpinned-uses]
  ↳ Recommendation: Pin it to a commit SHA with 'hx pin', or lock the workflow with 'gh actions-lock'.

.github/workflows/triage.yml:5: The workflow grants 'permissions: write-all' to every job. [excessive-permissions]
  ↳ Recommendation: Set 'permissions: contents: read' and give each job that writes only the scopes it needs.

.github/workflows/triage.yml:11: jobs.label.steps[1] expands github.event.issue.title into a script; a crafted value can run arbitrary commands with the job's token and secrets. [template-injection]
  ↳ Recommendation: Pass the value through 'env:' (for example 'TITLE: \${{ github.event.issue.title }}') and use "$TITLE" in the script.

Silence a finding you accept with '# hx: ignore[<rule-id>]' on the flagged line.`,
  },
  {
    cmd: 'hx pin',
    title: 'Pin actions to SHAs',
    desc: 'Rewrites uses: x@v7 to uses: x@<sha>  # v7 in every workflow, line by line so comments stay. Refs are resolved with git ls-remote; this is the only command that uses the network. --dry-run previews the changes.',
    snippet: `$ hx pin --dry-run
.github/workflows/ci.yml:34 actions/checkout@v7 → 3d3c42e5aac5ba805825da76410c181273ba90b1
.github/workflows/ci.yml:38 astral-sh/setup-uv@v10.4.0 → 1db35dd8eee11c5894872e0b383ae6c406cf738d
.github/workflows/ci.yml:42 actions/setup-python@v7.1.0 → 6d4fd22b20465ccc0f7354476588e8df7c9ca0e0

Dry run: would pin 3 action ref(s) in 1 file(s).`,
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
