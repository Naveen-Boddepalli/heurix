import type {
  ContainerContext,
  DeploymentTarget,
  DriftFinding,
  HeurixPolicy,
  LanguageContext,
  MonorepoPackage,
  ProjectContext,
  ScanResult,
  ServiceRequirement,
  VirtualFile,
} from './types';

const SENSITIVE_KEYWORDS = [
  'SECRET',
  'PASSWORD',
  'TOKEN',
  'KEY',
  'AUTH',
  'PRIVATE',
  'CREDENTIAL',
  'CERT',
  'URL',
  'URI',
  'DSN',
  'CONN',
  'WEBHOOK',
  'SESSION',
];

/** Deployment-only secret prefixes: kept out of test jobs and k8s/secret.yaml. */
const DEPLOYMENT_SECRET_PREFIXES = ['VERCEL_', 'FIREBASE_', 'AWS_', 'DOCKER_'];

function isDeploymentSecret(key: string): boolean {
  const upper = key.toUpperCase();
  return DEPLOYMENT_SECRET_PREFIXES.some((p) => upper.startsWith(p));
}

/** Default action refs, mirroring ACTION_VERSIONS in synthesizers/github_actions.py. */
export const ACTION_VERSIONS: Record<string, string> = {
  'actions/checkout': 'v7',
  'astral-sh/setup-uv': 'v10.4.0',
  'actions/setup-python': 'v7.1.0',
  'snok/install-poetry': 'v1',
  'pnpm/action-setup': 'v6',
  'actions/setup-node': 'v7',
  'oven-sh/setup-bun': 'v2',
  'dtolnay/rust-toolchain': 'stable',
  'Swatinem/rust-cache': 'v2',
  'actions/setup-go': 'v7',
  'amondnet/vercel-action': 'v25',
  'FirebaseExtended/action-hosting-deploy': 'v0',
};

function uses(repo: string): string {
  return `        uses: ${repo}@${ACTION_VERSIONS[repo] ?? 'v4'}`;
}

/** Quote a YAML scalar when it starts with a character YAML would misread. */
function yamlScalar(value: string): string {
  return /^[*!&{}[\]|>@`'"%#,?:-]/.test(value) || /: | #/.test(value)
    ? `'${value.replace(/'/g, "''")}'`
    : value;
}

// --------------------------------------------------------------------------
// Minimal `.heurix.toml` reader (sections, strings, booleans, string arrays)
// --------------------------------------------------------------------------

type TomlValue = string | boolean | number | string[];

function parseTomlValue(raw: string, lineNo: number): TomlValue {
  const v = raw.trim();
  if (v === 'true' || v === 'false') return v === 'true';
  if (/^-?\d+$/.test(v)) return Number(v);
  const str = v.match(/^"((?:[^"\\]|\\.)*)"$/) ?? v.match(/^'([^']*)'$/);
  if (str) return str[1];
  if (v.startsWith('[') && v.endsWith(']')) {
    const inner = v.slice(1, -1).trim();
    if (!inner) return [];
    const items: string[] = [];
    const re = /\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')\s*(?:,|$)/y;
    let m: RegExpExecArray | null;
    let consumed = 0;
    while (consumed < inner.length && (m = re.exec(inner))) {
      items.push(m[1] ?? m[2]);
      consumed = re.lastIndex;
    }
    if (consumed < inner.trim().length) {
      throw new Error(`line ${lineNo}: arrays may only contain quoted strings`);
    }
    return items;
  }
  throw new Error(`line ${lineNo}: invalid value '${v}'`);
}

function stripTomlComment(line: string): string {
  let inStr: string | null = null;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (inStr) {
      if (ch === inStr && line[i - 1] !== '\\') inStr = null;
    } else if (ch === '"' || ch === "'") {
      inStr = ch;
    } else if (ch === '#') {
      return line.slice(0, i);
    }
  }
  return line;
}

export function parseHeurixToml(text: string): Record<string, Record<string, TomlValue>> {
  const out: Record<string, Record<string, TomlValue>> = { '': {} };
  let section = '';
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    let line = stripTomlComment(lines[i]).trim();
    if (!line) continue;
    const header = line.match(/^\[\s*([A-Za-z0-9_.-]+)\s*\]$/);
    if (header) {
      section = header[1];
      out[section] ??= {};
      continue;
    }
    const eq = line.indexOf('=');
    if (eq === -1) throw new Error(`line ${i + 1}: expected 'key = value'`);
    const key = line.slice(0, eq).trim().replace(/^"|"$/g, '');
    let value = line.slice(eq + 1).trim();
    // Multi-line arrays
    if (value.startsWith('[') && !value.endsWith(']')) {
      const start = i + 1;
      while (i + 1 < lines.length && !value.endsWith(']')) {
        i += 1;
        line = stripTomlComment(lines[i]).trim();
        value += ` ${line}`;
      }
      if (!value.endsWith(']')) throw new Error(`line ${start}: unterminated array`);
      value = value.replace(/,\s*]$/, ']');
    }
    if (!key) throw new Error(`line ${i + 1}: missing key`);
    out[section][key] = parseTomlValue(value, i + 1);
  }
  return out;
}

function emptyPolicy(): HeurixPolicy {
  return {
    source: null,
    error: null,
    runner: null,
    includeK8s: null,
    includeDependabot: true,
    paths: null,
    pathsIgnore: [],
    imageTag: null,
    overrides: {},
  };
}

function asStringList(v: TomlValue | undefined, key: string): string[] | null {
  if (v === undefined) return null;
  if (typeof v === 'string') return [v];
  if (Array.isArray(v)) return Array.from(new Set(v));
  throw new Error(`[ci].${key} must be a string or a list of strings`);
}

function loadPolicy(indexer: VirtualRepoIndexer): HeurixPolicy {
  const policy = emptyPolicy();
  const raw = indexer.readText('.heurix.toml');
  if (raw === null) return policy;
  policy.source = '.heurix.toml';
  try {
    const doc = parseHeurixToml(raw);
    const engine = doc.engine ?? {};
    const ci = doc.ci ?? {};
    const k8s = doc.kubernetes ?? doc.k8s ?? {};
    if (typeof engine.runner === 'string' && engine.runner.trim()) policy.runner = engine.runner.trim();
    if (typeof ci.include_k8s === 'boolean') policy.includeK8s = ci.include_k8s;
    if (typeof ci.include_dependabot === 'boolean') policy.includeDependabot = ci.include_dependabot;
    policy.paths = asStringList(ci.paths, 'paths');
    policy.pathsIgnore = asStringList(ci.paths_ignore ?? ci['paths-ignore'], 'paths_ignore') ?? [];
    if (typeof k8s.image_tag === 'string') policy.imageTag = k8s.image_tag;
    for (const [lang, val] of Object.entries(doc.overrides ?? {})) {
      if (typeof val === 'string' || typeof val === 'number') policy.overrides[lang] = String(val);
    }
  } catch (err) {
    return { ...emptyPolicy(), source: '.heurix.toml', error: (err as Error).message };
  }
  return policy;
}

class VirtualRepoIndexer {
  private fileMap: Map<string, string>;
  public files: string[];

  constructor(virtualFiles: VirtualFile[]) {
    this.fileMap = new Map();
    for (const f of virtualFiles) {
      if (f.enabled) {
        this.fileMap.set(f.path, f.content);
      }
    }
    this.files = Array.from(this.fileMap.keys());
  }

  hasFile(path: string): boolean {
    return this.fileMap.has(path);
  }

  readText(path: string): string | null {
    return this.fileMap.get(path) ?? null;
  }

  findBySuffix(suffix: string): string[] {
    return this.files.filter((f) => f.endsWith(suffix));
  }

  findByName(filename: string): string[] {
    return this.files.filter((f) => f === filename || f.endsWith(`/${filename}`));
  }
}

function addServiceIfMissing(context: ProjectContext, svc: ServiceRequirement, explain: string): void {
  if (!context.services.some((s) => s.name === svc.name)) {
    context.services.push(svc);
    context.explain_log.push(explain);
  }
}

function addSecretIfMissing(context: ProjectContext, secret: string): void {
  if (!context.required_secrets.includes(secret)) {
    context.required_secrets.push(secret);
  }
}

function detectPython(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  const indicators = [
    'pyproject.toml',
    'requirements.txt',
    'Pipfile',
    'setup.py',
    'setup.cfg',
    '.python-version',
    'uv.lock',
    'poetry.lock',
  ];
  const hasPython = indicators.some((f) => indexer.hasFile(f)) || indexer.findBySuffix('.py').length > 0;
  if (!hasPython) return;

  context.explain_log.push('Analyzing Python ecosystem...');

  let runtimeVersion = '3.12';
  let versionSource = 'default';

  const pyVerFile = indexer.readText('.python-version');
  const toolVerFile = indexer.readText('.tool-versions');
  const pyproject = indexer.readText('pyproject.toml');

  if (pyVerFile) {
    const match = pyVerFile.trim().match(/(\d+\.\d+)/);
    if (match) {
      runtimeVersion = match[1];
      versionSource = '.python-version';
    }
  } else if (toolVerFile) {
    const match = toolVerFile.match(/python\s+(\d+\.\d+)/);
    if (match) {
      runtimeVersion = match[1];
      versionSource = '.tool-versions';
    }
  } else if (pyproject) {
    const reqMatch = pyproject.match(/(?:requires-python|python)\s*=\s*["'][^"']*?(\d+\.\d+)/);
    if (reqMatch) {
      runtimeVersion = reqMatch[1];
      versionSource = 'pyproject.toml';
    }
  }

  context.explain_log.push(`Detected Python ${runtimeVersion} (via ${versionSource})`);

  let packageManager = 'pip';
  let installCmd = '';

  const syncFlags: string[] = [];
  if (pyproject?.includes('[project.optional-dependencies]')) syncFlags.push('--all-extras');
  if (pyproject?.includes('[dependency-groups]')) syncFlags.push('--all-groups');

  if (indexer.hasFile('uv.lock')) {
    packageManager = 'uv';
    installCmd = ['uv sync --frozen', ...syncFlags].join(' ');
    context.explain_log.push('Detected Package Manager: uv (via uv.lock)');
  } else if (indexer.hasFile('poetry.lock')) {
    packageManager = 'poetry';
    installCmd = 'poetry install --no-interaction';
    context.explain_log.push('Detected Package Manager: poetry (via poetry.lock)');
  } else if (indexer.hasFile('Pipfile.lock') || indexer.hasFile('Pipfile')) {
    packageManager = 'pipenv';
    installCmd = 'pipenv install --deploy';
    context.explain_log.push('Detected Package Manager: pipenv (via Pipfile)');
  } else if (indexer.hasFile('requirements.txt')) {
    packageManager = 'pip';
    installCmd = indexer.hasFile('requirements-dev.txt')
      ? 'pip install -r requirements.txt -r requirements-dev.txt'
      : 'pip install -r requirements.txt';
    context.explain_log.push('Detected Package Manager: pip (via requirements.txt)');
  } else if (pyproject) {
    packageManager = 'pip';
    if (pyproject.includes('[project.optional-dependencies]') && pyproject.includes('dev')) {
      installCmd = "pip install -e '.[dev]'";
    } else if (pyproject.includes('[project.optional-dependencies]') && pyproject.includes('test')) {
      installCmd = "pip install -e '.[test]'";
    } else {
      installCmd = 'pip install -e .';
    }
    context.explain_log.push(`Detected Package Manager: pip (via pyproject.toml, cmd: ${installCmd})`);
  }

  const depsText = ['pyproject.toml', 'requirements.txt', 'Pipfile', 'setup.py']
    .map((f) => indexer.readText(f) ?? '')
    .join('\n');
  const depsLower = depsText.toLowerCase();

  if (!installCmd) {
    installCmd = 'python -m pip install --upgrade pip' + (depsLower.includes('pytest') ? ' pytest' : '');
    context.explain_log.push('No lockfile or manifest found; using minimal pip setup');
  }

  const cmdPrefix = packageManager === 'uv' ? 'uv run ' : packageManager === 'poetry' ? 'poetry run ' : '';

  let framework: string | null = null;
  if (depsLower.includes('fastapi')) framework = 'FastAPI';
  else if (depsLower.includes('streamlit')) framework = 'Streamlit';
  else if (depsLower.includes('django')) framework = 'Django';
  else if (depsLower.includes('flask')) framework = 'Flask';

  if (framework) {
    context.explain_log.push(`Detected Framework: ${framework}`);
  }

  let testCmd = 'python -m unittest discover';
  if (depsLower.includes('pytest') || indexer.hasFile('pytest.ini') || depsText.includes('[tool.pytest')) {
    // `python -m pytest` puts the repo root on sys.path, so flat layouts import.
    testCmd = 'python -m pytest';
    context.explain_log.push('Detected Test Runner: pytest (run as python -m pytest)');
  } else if (depsLower.includes('django') && indexer.hasFile('manage.py')) {
    testCmd = 'python manage.py test';
    context.explain_log.push('Detected Test Runner: django manage.py test');
  }

  let lintCmd: string | null = null;
  if (depsLower.includes('ruff') || depsText.includes('[tool.ruff')) {
    lintCmd = 'ruff check .';
    context.explain_log.push('Detected Linter: ruff');
  } else if (depsLower.includes('flake8')) {
    lintCmd = 'flake8 .';
    context.explain_log.push('Detected Linter: flake8');
  }

  testCmd = `${cmdPrefix}${testCmd}`;
  if (lintCmd) lintCmd = `${cmdPrefix}${lintCmd}`;

  if (['psycopg', 'asyncpg', 'postgresql', 'pgvector'].some((d) => depsLower.includes(d))) {
    addServiceIfMissing(
      context,
      {
        name: 'postgres',
        image: 'postgres:16-alpine',
        ports: [5432],
        env: {
          POSTGRES_USER: 'test_user',
          POSTGRES_PASSWORD: 'test_password',
          POSTGRES_DB: 'test_db',
        },
        source_file: 'python dependencies',
      },
      'Inferred Backing Service: PostgreSQL 16 (via python postgres client)'
    );
  }

  if (['redis', 'aioredis', 'celery'].some((r) => depsLower.includes(r))) {
    addServiceIfMissing(
      context,
      {
        name: 'redis',
        image: 'redis:7-alpine',
        ports: [6379],
        env: {},
        source_file: 'python dependencies',
      },
      'Inferred Backing Service: Redis 7 (via python redis client/celery)'
    );
  }

  const lang: LanguageContext = {
    language: 'python',
    runtime_version: runtimeVersion,
    version_source: versionSource,
    package_manager: packageManager,
    install_cmd: installCmd,
    build_cmd: null,
    test_cmd: testCmd,
    lint_cmd: lintCmd,
    working_dir: '.',
    framework,
    confidence: versionSource !== 'default' ? 0.98 : 0.85,
  };
  context.languages.push(lang);
}

function detectNode(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  const indicators = ['package.json', '.nvmrc', '.node-version', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lockb'];
  if (!indicators.some((f) => indexer.hasFile(f))) return;

  context.explain_log.push('Analyzing Node.js / JavaScript / TypeScript ecosystem...');

  let nodeVersion = '20.x';
  let versionSource = 'default';

  const nvmrc = indexer.readText('.nvmrc');
  const nodeVerFile = indexer.readText('.node-version');

  if (nvmrc) {
    const m = nvmrc.trim().replace(/^v/, '').match(/^(\d+)/);
    if (m) {
      nodeVersion = `${m[1]}.x`;
      versionSource = '.nvmrc';
    }
  } else if (nodeVerFile) {
    const m = nodeVerFile.trim().replace(/^v/, '').match(/^(\d+)/);
    if (m) {
      nodeVersion = `${m[1]}.x`;
      versionSource = '.node-version';
    }
  }

  let pkgData: Record<string, unknown> = {};
  const rawPkg = indexer.readText('package.json');
  if (rawPkg) {
    try {
      pkgData = JSON.parse(rawPkg) as Record<string, unknown>;
    } catch {
      pkgData = {};
    }
  }

  const engines = pkgData.engines as Record<string, string> | undefined;
  if (versionSource === 'default' && engines?.node) {
    const m = String(engines.node).match(/(\d+)/);
    if (m) {
      nodeVersion = `${m[1]}.x`;
      versionSource = 'package.json (engines)';
    }
  }

  context.explain_log.push(`Detected Node.js ${nodeVersion} (via ${versionSource})`);

  let packageManager = 'npm';
  let installCmd = 'npm install';

  if (indexer.hasFile('pnpm-lock.yaml')) {
    packageManager = 'pnpm';
    installCmd = 'pnpm i --frozen-lockfile';
    context.explain_log.push('Detected Package Manager: pnpm (via pnpm-lock.yaml)');
  } else if (indexer.hasFile('yarn.lock')) {
    packageManager = 'yarn';
    installCmd = 'yarn install --frozen-lockfile';
    context.explain_log.push('Detected Package Manager: yarn (via yarn.lock)');
  } else if (indexer.hasFile('bun.lockb') || indexer.hasFile('bun.lock')) {
    packageManager = 'bun';
    installCmd = 'bun install --frozen-lockfile';
    context.explain_log.push('Detected Package Manager: bun (via bun.lock)');
  } else if (indexer.hasFile('package-lock.json')) {
    packageManager = 'npm';
    installCmd = 'npm ci';
    context.explain_log.push('Detected Package Manager: npm (via package-lock.json)');
  } else {
    context.explain_log.push('Detected Package Manager: npm');
  }

  let isMonorepo = false;
  if (indexer.hasFile('pnpm-workspace.yaml')) {
    isMonorepo = true;
    context.explain_log.push('Detected Monorepo Topology: pnpm-workspace.yaml');
  } else if (indexer.hasFile('turbo.json')) {
    isMonorepo = true;
    context.explain_log.push('Detected Monorepo Topology: Turborepo (turbo.json)');
  } else if (indexer.hasFile('nx.json')) {
    isMonorepo = true;
    context.explain_log.push('Detected Monorepo Topology: Nx (nx.json)');
  } else if ('workspaces' in pkgData) {
    isMonorepo = true;
    context.explain_log.push('Detected Monorepo Topology: npm/yarn workspaces');
  }

  if (isMonorepo) {
    context.is_monorepo = true;
    const subPkgs = indexer.findByName('package.json').filter((p) => p !== 'package.json');
    for (const p of subPkgs) {
      const subDir = p.slice(0, p.lastIndexOf('/'));
      const pkgEntry: MonorepoPackage = {
        name: subDir,
        path: subDir,
        language: 'node',
        package_manager: packageManager,
      };
      context.monorepo_packages.push(pkgEntry);
    }
    if (context.monorepo_packages.length > 0) {
      context.explain_log.push(
        `Discovered ${context.monorepo_packages.length} monorepo sub-package(s): ${context.monorepo_packages
          .map((m) => m.path)
          .join(', ')}`
      );
    }
  }

  const allDeps: Record<string, string> = {
    ...((pkgData.dependencies as Record<string, string>) ?? {}),
    ...((pkgData.devDependencies as Record<string, string>) ?? {}),
  };
  const scripts = (pkgData.scripts as Record<string, string>) ?? {};
  const depNames = Object.keys(allDeps).map((k) => k.toLowerCase());

  let framework: string | null = null;
  if (depNames.includes('next')) framework = 'Next.js';
  else if (depNames.includes('nuxt')) framework = 'Nuxt';
  else if (depNames.includes('@nestjs/core')) framework = 'NestJS';
  else if (depNames.includes('express')) framework = 'Express';
  else if (depNames.includes('vite')) framework = 'Vite';

  if (framework) {
    context.explain_log.push(`Detected Framework: ${framework}`);
  }

  const runPrefix =
    packageManager === 'pnpm'
      ? 'pnpm '
      : packageManager === 'yarn'
        ? 'yarn '
        : packageManager === 'bun'
          ? 'bun run '
          : 'npm run ';

  const buildCmd = scripts.build ? `${runPrefix}build` : null;
  const lintCmd = scripts.lint ? `${runPrefix}lint` : null;
  let testCmd: string | null = null;
  if (scripts.test) {
    testCmd = packageManager === 'npm' ? 'npm test' : `${runPrefix}test`;
    context.explain_log.push(`Detected Test Script: ${testCmd}`);
  } else if (depNames.includes('vitest')) {
    testCmd = 'npx vitest run';
  } else if (depNames.includes('jest')) {
    testCmd = 'npx jest';
  }

  if (['pg', 'prisma', '@prisma/client', 'typeorm'].some((d) => depNames.includes(d))) {
    addServiceIfMissing(
      context,
      {
        name: 'postgres',
        image: 'postgres:16-alpine',
        ports: [5432],
        env: {
          POSTGRES_USER: 'test_user',
          POSTGRES_PASSWORD: 'test_password',
          POSTGRES_DB: 'test_db',
        },
        source_file: 'package.json',
      },
      'Inferred Backing Service: PostgreSQL 16 (via package.json)'
    );
  }

  if (['redis', 'ioredis', 'bullmq'].some((r) => depNames.includes(r))) {
    addServiceIfMissing(
      context,
      {
        name: 'redis',
        image: 'redis:7-alpine',
        ports: [6379],
        env: {},
        source_file: 'package.json',
      },
      'Inferred Backing Service: Redis 7 (via package.json)'
    );
  }

  if (['mongoose', 'mongodb'].some((m) => depNames.includes(m))) {
    addServiceIfMissing(
      context,
      {
        name: 'mongodb',
        image: 'mongo:7',
        ports: [27017],
        env: {},
        source_file: 'package.json',
      },
      'Inferred Backing Service: MongoDB 7 (via package.json)'
    );
  }

  context.languages.push({
    language: 'node',
    runtime_version: nodeVersion,
    version_source: versionSource,
    package_manager: packageManager,
    install_cmd: installCmd,
    build_cmd: buildCmd,
    test_cmd: testCmd,
    lint_cmd: lintCmd,
    working_dir: '.',
    framework,
    confidence: versionSource !== 'default' ? 0.98 : 0.88,
  });
}

function detectRust(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  if (!indexer.hasFile('Cargo.toml') && !indexer.hasFile('rust-toolchain.toml')) return;
  context.explain_log.push('Analyzing Rust ecosystem...');

  let rustVersion = 'stable';
  let versionSource = 'default';

  const rtToml = indexer.readText('rust-toolchain.toml');
  const rtPlain = indexer.readText('rust-toolchain');
  if (rtToml) {
    const m = rtToml.match(/channel\s*=\s*["']([^"']+)["']/);
    if (m) {
      rustVersion = m[1];
      versionSource = 'rust-toolchain.toml';
    }
  } else if (rtPlain && rtPlain.trim()) {
    rustVersion = rtPlain.trim();
    versionSource = 'rust-toolchain';
  }

  context.explain_log.push(`Detected Rust toolchain: ${rustVersion} (via ${versionSource})`);

  const cargo = indexer.readText('Cargo.toml') ?? '';
  let framework: string | null = null;
  if (cargo.includes('actix-web')) framework = 'Actix-Web';
  else if (cargo.includes('axum')) framework = 'Axum';
  else if (cargo.includes('rocket')) framework = 'Rocket';

  if (framework) {
    context.explain_log.push(`Detected Framework: ${framework}`);
  }

  context.languages.push({
    language: 'rust',
    runtime_version: rustVersion,
    version_source: versionSource,
    package_manager: 'cargo',
    install_cmd: 'cargo fetch',
    build_cmd: 'cargo build --release',
    test_cmd: 'cargo test --verbose',
    lint_cmd: 'cargo clippy -- -D warnings',
    working_dir: '.',
    framework,
    confidence: 0.98,
  });
}

function detectGo(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  if (!indexer.hasFile('go.mod') && indexer.findBySuffix('.go').length === 0) return;
  context.explain_log.push('Analyzing Go ecosystem...');

  let goVersion = '1.22';
  let versionSource = 'default';
  const goMod = indexer.readText('go.mod') ?? '';

  if (goMod) {
    const m = goMod.match(/^go\s+([0-9]+(?:\.[0-9]+)?)/m);
    if (m) {
      goVersion = m[1];
      versionSource = 'go.mod';
    }
  }

  context.explain_log.push(`Detected Go version: ${goVersion} (via ${versionSource})`);

  let framework: string | null = null;
  if (goMod.includes('github.com/gin-gonic/gin')) framework = 'Gin';
  else if (goMod.includes('github.com/labstack/echo')) framework = 'Echo';
  else if (goMod.includes('github.com/gofiber/fiber')) framework = 'Fiber';

  if (framework) {
    context.explain_log.push(`Detected Framework: ${framework}`);
  }

  context.languages.push({
    language: 'go',
    runtime_version: goVersion,
    version_source: versionSource,
    package_manager: 'gomod',
    install_cmd: 'go mod download',
    build_cmd: 'go build -v ./...',
    test_cmd: 'go test -v -race -cover ./...',
    lint_cmd: 'golangci-lint run',
    working_dir: '.',
    framework,
    confidence: 0.95,
  });
}

function detectCpp(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  const indicators = ['CMakeLists.txt', 'conanfile.txt', 'conanfile.py', 'vcpkg.json'];
  const hasCppSources = ['.cpp', '.cc', '.hpp', '.c', '.h'].some(
    (ext) => indexer.findBySuffix(ext).length > 0
  );
  if (!indicators.some((f) => indexer.hasFile(f)) && !hasCppSources) return;

  context.explain_log.push('Analyzing C / C++ ecosystem...');

  let packageManager = 'cmake';
  let installCmd = '';
  let buildCmd = 'cmake -B build -S . && cmake --build build';
  let testCmd = 'ctest --test-dir build --output-on-failure';
  let runtimeVersion = 'latest';
  let versionSource = 'system';

  if (indexer.hasFile('conanfile.txt') || indexer.hasFile('conanfile.py')) {
    packageManager = 'conan';
    installCmd = 'conan install . --output-folder=build --build=missing';
    context.explain_log.push('Detected Package Manager: Conan');
  } else if (indexer.hasFile('vcpkg.json')) {
    packageManager = 'vcpkg';
    installCmd = 'vcpkg install';
    context.explain_log.push('Detected Package Manager: vcpkg');
  } else if (indexer.hasFile('CMakeLists.txt')) {
    packageManager = 'cmake';
    installCmd = 'cmake -B build -S . -DCMAKE_EXPORT_COMPILE_COMMANDS=ON';
    buildCmd = 'cmake -B build -S . -DCMAKE_EXPORT_COMPILE_COMMANDS=ON && cmake --build build';
    context.explain_log.push('Detected Build Tool: CMake (via CMakeLists.txt)');
    const cmake = indexer.readText('CMakeLists.txt') ?? '';
    const stdMatch = cmake.match(/set\s*\(\s*CMAKE_CXX_STANDARD\s+(\d+)\s*\)/i);
    if (stdMatch) {
      runtimeVersion = `c++${stdMatch[1]}`;
      versionSource = 'CMakeLists.txt';
      context.explain_log.push(`Detected C++ Standard: ${runtimeVersion} (via CMakeLists.txt)`);
    }
  } else if (indexer.hasFile('Makefile')) {
    packageManager = 'make';
    buildCmd = 'make';
    testCmd = 'make test';
    context.explain_log.push('Detected Build Tool: Make (via Makefile)');
  }

  let lintCmd: string | null = null;
  if (indexer.hasFile('.clang-tidy')) {
    lintCmd = 'clang-tidy -p build';
    context.explain_log.push('Detected Linter: clang-tidy (via .clang-tidy)');
  }

  context.languages.push({
    language: 'cpp',
    runtime_version: runtimeVersion,
    version_source: versionSource,
    package_manager: packageManager,
    install_cmd: installCmd || "echo 'No package manager'",
    build_cmd: buildCmd,
    test_cmd: testCmd,
    lint_cmd: lintCmd,
    working_dir: '.',
    framework: null,
    confidence: 0.9,
  });
}

function detectDocker(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  const composeFiles = ['docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml'].filter((f) =>
    indexer.hasFile(f)
  );
  const hasDocker = indexer.hasFile('Dockerfile') || composeFiles.length > 0;
  if (!hasDocker) return;

  context.explain_log.push('Analyzing Docker configurations...');

  const df = indexer.readText('Dockerfile');
  if (df) {
    const exposedPorts: number[] = [];
    let baseImage = '';
    let buildTarget: string | null = null;
    const hasHealthcheck = /^\s*HEALTHCHECK/m.test(df);

    for (const rawLine of df.split('\n')) {
      const line = rawLine.trim();
      if (line.toUpperCase().startsWith('FROM ')) {
        const parts = line.split(/\s+/);
        if (parts.length >= 2) {
          baseImage = parts[1];
          const upper = parts.map((p) => p.toUpperCase());
          const asIdx = upper.indexOf('AS');
          buildTarget = asIdx !== -1 && asIdx + 1 < parts.length ? parts[asIdx + 1] : null;
        }
      } else if (line.toUpperCase().startsWith('EXPOSE ')) {
        const portTokens = line.replace(/^EXPOSE\s+/i, '').split(/\s+/);
        for (const p of portTokens) {
          const clean = p.split('/')[0];
          if (/^\d+$/.test(clean)) {
            exposedPorts.push(Number(clean));
          }
        }
      }
    }

    const container: ContainerContext = {
      dockerfile_path: 'Dockerfile',
      exposed_ports: exposedPorts,
      base_image: baseImage,
      has_healthcheck: hasHealthcheck,
      build_target: buildTarget,
    };
    context.containers.push(container);
    context.explain_log.push(
      `Parsed Dockerfile 'Dockerfile': base=${baseImage}, exposed=[${exposedPorts.join(', ')}], healthcheck=${hasHealthcheck}, build_target=${buildTarget ?? 'none'}`
    );
  }

  for (const cf of composeFiles) {
    const content = indexer.readText(cf) ?? '';
    if (content.includes('postgres')) {
      const imgMatch = content.match(/image:\s*["']?(postgres[^\s"']+)/);
      addServiceIfMissing(
        context,
        {
          name: 'postgres',
          image: imgMatch ? imgMatch[1] : 'postgres:16-alpine',
          ports: [5432],
          env: {
            POSTGRES_USER: 'test_user',
            POSTGRES_PASSWORD: 'test_password',
            POSTGRES_DB: 'test_db',
          },
          source_file: cf,
        },
        `Detected Backing Service: postgres (via ${cf})`
      );
    }
    if (content.includes('redis')) {
      const imgMatch = content.match(/image:\s*["']?(redis[^\s"']+)/);
      addServiceIfMissing(
        context,
        {
          name: 'redis',
          image: imgMatch ? imgMatch[1] : 'redis:7-alpine',
          ports: [6379],
          env: {},
          source_file: cf,
        },
        `Detected Backing Service: redis (via ${cf})`
      );
    }
    if (content.includes('mongo')) {
      const imgMatch = content.match(/image:\s*["']?(mongo[^\s"']+)/);
      addServiceIfMissing(
        context,
        {
          name: 'mongodb',
          image: imgMatch ? imgMatch[1] : 'mongo:7',
          ports: [27017],
          env: {},
          source_file: cf,
        },
        `Detected Backing Service: mongodb (via ${cf})`
      );
    }
  }
}

function detectEnv(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  const candidates = ['.env.example', '.env.template', '.env.sample', '.env.dist', '.env.local.example'];
  const envFiles = candidates.filter((f) => indexer.hasFile(f));
  if (envFiles.length === 0) return;

  context.explain_log.push('Analyzing environment templates and secret definitions...');
  const foundSecrets = new Set<string>();

  for (const ef of envFiles) {
    const content = indexer.readText(ef) ?? '';
    for (const rawLine of content.split('\n')) {
      const line = rawLine.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const eqIdx = line.indexOf('=');
      const key = line.slice(0, eqIdx).trim();
      const val = line.slice(eqIdx + 1).trim().replace(/^['"]|['"]$/g, '');
      const isSensitive = SENSITIVE_KEYWORDS.some((kw) => key.toUpperCase().includes(kw));
      if (isSensitive) {
        foundSecrets.add(key);
      } else {
        context.env_vars[key] = val;
      }
    }
    context.explain_log.push(
      `Scanned ${ef}: discovered ${Object.keys(context.env_vars).length} env defaults and ${foundSecrets.size} potential secrets`
    );
  }

  for (const s of Array.from(foundSecrets).sort()) {
    addSecretIfMissing(context, s);
    context.explain_log.push(`Wired sensitive secret: ${s} -> \${{ secrets.${s} }}`);
  }
}

function detectCloud(indexer: VirtualRepoIndexer, context: ProjectContext): void {
  const hasVercel = indexer.hasFile('vercel.json') || indexer.hasFile('.vercel');
  const hasFirebase = indexer.hasFile('firebase.json') || indexer.hasFile('.firebaserc');
  if (!hasVercel && !hasFirebase) return;

  context.explain_log.push('Analyzing cloud deployment targets...');

  if (hasVercel) {
    let vercelCfg: Record<string, unknown> = {};
    const raw = indexer.readText('vercel.json');
    if (raw) {
      try {
        vercelCfg = JSON.parse(raw) as Record<string, unknown>;
      } catch {
        vercelCfg = {};
      }
    }
    const projectName = (vercelCfg.name as string | undefined) ?? context.repo_name;
    const framework = (vercelCfg.framework as string | undefined) ?? 'auto';
    const features = ['hosting'];
    if (vercelCfg.functions || indexer.files.some((f) => f.startsWith('api/'))) {
      features.push('serverless');
    }
    const secrets = ['VERCEL_TOKEN', 'VERCEL_ORG_ID', 'VERCEL_PROJECT_ID'];
    secrets.forEach((s) => addSecretIfMissing(context, s));

    const target: DeploymentTarget = {
      platform: 'vercel',
      config_file: indexer.hasFile('vercel.json') ? 'vercel.json' : '.vercel',
      project_id: projectName,
      features,
      deploy_cmd: 'vercel --prod',
      preview_deploy_cmd: 'vercel',
      required_secrets: secrets,
    };
    context.deployment_targets.push(target);
    context.explain_log.push(
      `Detected Vercel target (project: '${projectName}', framework: ${framework}, features: [${features.join(', ')}])`
    );
  }

  if (hasFirebase) {
    let fbCfg: Record<string, unknown> = {};
    const rawFb = indexer.readText('firebase.json');
    if (rawFb) {
      try {
        fbCfg = JSON.parse(rawFb) as Record<string, unknown>;
      } catch {
        fbCfg = {};
      }
    }
    let projectId: string | null = null;
    const rawRc = indexer.readText('.firebaserc');
    if (rawRc) {
      try {
        const rcData = JSON.parse(rawRc) as { projects?: { default?: string } };
        projectId = rcData.projects?.default ?? null;
      } catch {
        projectId = null;
      }
    }
    projectId = projectId ?? context.repo_name;

    const features: string[] = [];
    for (const feat of ['hosting', 'functions', 'firestore', 'storage', 'emulators', 'remoteconfig']) {
      if (feat in fbCfg) features.push(feat);
    }
    if (features.length === 0) features.push('hosting');

    const secrets = ['FIREBASE_SERVICE_ACCOUNT'];
    secrets.forEach((s) => addSecretIfMissing(context, s));

    const target: DeploymentTarget = {
      platform: 'firebase',
      config_file: indexer.hasFile('firebase.json') ? 'firebase.json' : '.firebaserc',
      project_id: projectId,
      features,
      deploy_cmd: features.length === 1 && features[0] === 'hosting' ? 'firebase deploy --only hosting' : 'firebase deploy',
      preview_deploy_cmd: 'firebase hosting:channel:deploy preview',
      required_secrets: secrets,
    };
    context.deployment_targets.push(target);
    context.explain_log.push(
      `Detected Firebase target (project: '${projectId}', features: [${features.join(', ')}])`
    );
  }
}

function resolvePathFilters(
  context: ProjectContext,
  policy: HeurixPolicy
): { paths: string[] | null; pathsIgnore: string[] | null } {
  let paths: string[] | null =
    context.is_monorepo && context.monorepo_packages.length > 0 ? ['**'] : null;
  let pathsIgnore: string[] | null = null;
  // Explicit [ci].paths / [ci].paths_ignore policy wins over the inferred filter.
  if (policy.paths !== null) paths = policy.paths.length > 0 ? [...policy.paths] : null;
  if (policy.pathsIgnore.length > 0) {
    if (paths) {
      // GitHub rejects `paths` + `paths-ignore` on one event: fold ignores in as negations.
      paths = [...paths, ...policy.pathsIgnore.map((p) => `!${p}`)];
    } else {
      pathsIgnore = [...policy.pathsIgnore];
    }
  }
  return { paths, pathsIgnore };
}

function synthesizeGitHubActions(context: ProjectContext, policy: HeurixPolicy): string {
  const { paths, pathsIgnore } = resolvePathFilters(context, policy);
  const filterLines: string[] = [];
  if (paths) filterLines.push('    paths:', ...paths.map((p) => `      - ${yamlScalar(p)}`));
  if (pathsIgnore) filterLines.push('    paths-ignore:', ...pathsIgnore.map((p) => `      - ${yamlScalar(p)}`));

  const lines: string[] = [
    '# Synthesized deterministically by Heurix (hx)',
    '# Non-destructive updates: preserve blocks marked with # @heurix:preserve',
    'name: CI',
    'permissions:',
    '  contents: read',
    'on:',
    '  push:',
    '    branches:',
    '      - main',
    '      - master',
    ...filterLines,
    '  pull_request:',
    '    branches:',
    '      - main',
    '      - master',
    ...filterLines,
  ];

  lines.push('jobs:', '  test:', `    runs-on: ${context.runner}`);

  if (context.services.length > 0) {
    lines.push('    services:');
    for (const svc of context.services) {
      lines.push(`      ${svc.name.toLowerCase()}:`);
      lines.push(`        image: ${svc.image}`);
      if (Object.keys(svc.env).length > 0) {
        lines.push('        env:');
        for (const [k, v] of Object.entries(svc.env)) {
          lines.push(`          ${k}: ${v}`);
        }
      }
      if (svc.ports.length > 0) {
        lines.push('        ports:');
        for (const p of svc.ports) {
          lines.push(`          - ${p}:${p}`);
        }
      }
      if (svc.name.toLowerCase().includes('postgres')) {
        lines.push(
          '        options: --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5'
        );
      } else if (svc.name.toLowerCase().includes('redis')) {
        lines.push(
          '        options: --health-cmd "redis-cli ping" --health-interval 10s --health-timeout 5s --health-retries 5'
        );
      }
    }
  }

  lines.push('    steps:', '      - name: Checkout repository', uses('actions/checkout'));

  for (const lang of context.languages) {
    if (lang.language === 'python') {
      if (lang.package_manager === 'uv') {
        lines.push(
          '      - name: Install uv',
          uses('astral-sh/setup-uv'),
          '        with:',
          '          enable-cache: true',
          `      - name: Set up Python ${lang.runtime_version}`,
          uses('actions/setup-python'),
          '        with:',
          `          python-version: '${lang.runtime_version}'`,
          '      - name: Install dependencies',
          `        run: ${lang.install_cmd}`
        );
      } else if (lang.package_manager === 'poetry') {
        lines.push(
          `      - name: Set up Python ${lang.runtime_version}`,
          uses('actions/setup-python'),
          '        with:',
          `          python-version: '${lang.runtime_version}'`,
          '          cache: poetry',
          '      - name: Install Poetry',
          uses('snok/install-poetry'),
          '        with:',
          '          virtualenvs-create: true',
          '          virtualenvs-in-project: true',
          '      - name: Install dependencies',
          `        run: ${lang.install_cmd}`
        );
      } else {
        lines.push(
          `      - name: Set up Python ${lang.runtime_version}`,
          uses('actions/setup-python'),
          '        with:',
          `          python-version: '${lang.runtime_version}'`
        );
        if (lang.install_cmd.includes('requirements') || lang.install_cmd.includes('pip install -e')) {
          lines.push('          cache: pip');
        }
        lines.push('      - name: Install dependencies', `        run: ${lang.install_cmd}`);
      }
    } else if (lang.language === 'node') {
      if (lang.package_manager === 'pnpm') {
        lines.push(
          '      - name: Install pnpm',
          uses('pnpm/action-setup'),
          '        with:',
          "          version: '9'",
          `      - name: Set up Node.js ${lang.runtime_version}`,
          uses('actions/setup-node'),
          '        with:',
          `          node-version: ${lang.runtime_version}`,
          '          cache: pnpm'
        );
      } else if (lang.package_manager === 'bun') {
        lines.push(
          '      - name: Set up Bun',
          uses('oven-sh/setup-bun'),
          '        with:',
          '          bun-version: latest'
        );
      } else {
        lines.push(
          `      - name: Set up Node.js ${lang.runtime_version}`,
          uses('actions/setup-node'),
          '        with:',
          `          node-version: ${lang.runtime_version}`,
          `          cache: ${lang.package_manager === 'yarn' ? 'yarn' : 'npm'}`
        );
      }
      lines.push('      - name: Install dependencies', `        run: ${lang.install_cmd}`);
    } else if (lang.language === 'rust') {
      lines.push(
        `      - name: Set up Rust (${lang.runtime_version})`,
        '        uses: dtolnay/rust-toolchain@stable',
        '        with:',
        `          toolchain: ${lang.runtime_version}`,
        '      - name: Rust Cache',
        uses('Swatinem/rust-cache')
      );
    } else if (lang.language === 'go') {
      lines.push(
        `      - name: Set up Go ${lang.runtime_version}`,
        uses('actions/setup-go'),
        '        with:',
        `          go-version: '${lang.runtime_version}'`,
        '          cache: true',
        '      - name: Download Go dependencies',
        `        run: ${lang.install_cmd}`
      );
    } else if (lang.language === 'cpp') {
      const aptPkgs = lang.lint_cmd?.includes('clang-tidy')
        ? 'cmake ninja-build build-essential clang-tidy'
        : 'cmake ninja-build build-essential';
      lines.push(
        `      - name: Install build tools (${lang.runtime_version})`,
        `        run: sudo apt-get update && sudo apt-get install -y ${aptPkgs}`
      );
    }

    if (lang.language === 'cpp') {
      if (lang.build_cmd) {
        lines.push(`      - name: Build (${lang.language})`, `        run: ${lang.build_cmd}`);
      }
      if (lang.lint_cmd) {
        lines.push(`      - name: Lint code (${lang.language})`, `        run: ${lang.lint_cmd}`);
      }
    } else {
      if (lang.lint_cmd) {
        lines.push(`      - name: Lint code (${lang.language})`, `        run: ${lang.lint_cmd}`);
      }
      if (lang.build_cmd) {
        lines.push(`      - name: Build (${lang.language})`, `        run: ${lang.build_cmd}`);
      }
    }

    if (lang.test_cmd) {
      lines.push(`      - name: Run tests (${lang.language})`, `        run: ${lang.test_cmd}`);
      const envEntries = Object.entries(context.env_vars);
      const testSecrets = context.required_secrets.filter((s) => !isDeploymentSecret(s));
      if (envEntries.length > 0 || testSecrets.length > 0) {
        lines.push('        env:');
        for (const [k, v] of envEntries) {
          lines.push(`          ${k}: ${v}`);
        }
        for (const s of testSecrets) {
          lines.push(`          ${s}: \${{ secrets.${s} }}`);
        }
      }
    }
  }

  for (const target of context.deployment_targets) {
    if (target.platform === 'vercel') {
      lines.push(
        '  deploy_vercel:',
        '    name: Deploy to Vercel',
        '    needs: test',
        '    runs-on: ubuntu-latest',
        "    if: github.ref == 'refs/heads/main' && github.event_name == 'push'",
        '    steps:',
        '      - name: Checkout repository',
        uses('actions/checkout'),
        '      - name: Deploy to Vercel (Production)',
        uses('amondnet/vercel-action'),
        '        with:',
        '          vercel-token: ${{ secrets.VERCEL_TOKEN }}',
        '          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}',
        '          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}',
        '          vercel-args: --prod'
      );
    } else if (target.platform === 'firebase') {
      lines.push(
        '  deploy_firebase:',
        '    name: Deploy to Firebase',
        '    needs: test',
        '    runs-on: ubuntu-latest',
        "    if: github.ref == 'refs/heads/main' && github.event_name == 'push'",
        '    steps:',
        '      - name: Checkout repository',
        uses('actions/checkout'),
        '      - name: Deploy to Firebase Hosting',
        uses('FirebaseExtended/action-hosting-deploy'),
        '        with:',
        '          repoToken: ${{ secrets.GITHUB_TOKEN }}',
        '          firebaseServiceAccount: ${{ secrets.FIREBASE_SERVICE_ACCOUNT }}',
        `          projectId: ${target.project_id ?? context.repo_name}`,
        '          channelId: live'
      );
    }
  }

  return lines.join('\n') + '\n';
}

function synthesizeDependabot(context: ProjectContext): string {
  const lines = [
    '# Synthesized deterministically by Heurix (hx)',
    'version: 2',
    'updates:',
    '  - package-ecosystem: github-actions',
    '    directory: /',
    '    schedule:',
    '      interval: weekly',
    '    open-pull-requests-limit: 10',
  ];

  const seenEcosystems = new Set<string>();
  for (const lang of context.languages) {
    const eco =
      lang.language === 'python'
        ? 'pip'
        : lang.language === 'node'
          ? 'npm'
          : lang.language === 'rust'
            ? 'cargo'
            : lang.language === 'go'
              ? 'gomod'
              : null;

    if (eco && !seenEcosystems.has(eco)) {
      seenEcosystems.add(eco);
      lines.push(
        `  - package-ecosystem: ${eco}`,
        '    directory: /',
        '    schedule:',
        '      interval: weekly',
        '    open-pull-requests-limit: 10'
      );
    }

    if (lang.language === 'node') {
      for (const pkg of context.monorepo_packages) {
        lines.push(
          '  - package-ecosystem: npm',
          `    directory: /${pkg.path}`,
          '    schedule:',
          '      interval: weekly',
          '    open-pull-requests-limit: 5'
        );
      }
    }
  }

  if (context.containers.length > 0) {
    lines.push(
      '  - package-ecosystem: docker',
      '    directory: /',
      '    schedule:',
      '      interval: weekly',
      '    open-pull-requests-limit: 10'
    );
  }

  return lines.join('\n') + '\n';
}

function synthesizeKubernetes(context: ProjectContext, policy: HeurixPolicy): Record<string, string> {
  // Manifests only for containerized repos (or an explicit include_k8s = true policy):
  // a framework alone no longer produces a Deployment for an image nothing builds.
  if (policy.includeK8s === false) return {};
  if (context.containers.length === 0 && policy.includeK8s !== true) return {};

  const appName = context.repo_name.toLowerCase().replace(/_/g, '-');
  const primary = context.languages[0];
  const isStreamlit = primary?.framework === 'Streamlit';

  let port = 8080;
  if (isStreamlit) port = 8501;
  else if (context.containers[0]?.exposed_ports.length) port = context.containers[0].exposed_ports[0];
  else if (primary?.framework === 'FastAPI') port = 8000;
  else if (primary?.framework === 'Next.js' || primary?.framework === 'Express') port = 3000;

  const isSystems = primary?.language === 'go' || primary?.language === 'rust';
  const cpuReq = isSystems ? '50m' : '100m';
  const memReq = isSystems ? '64Mi' : '256Mi';
  const memLimit = isSystems ? '256Mi' : '512Mi';

  // Deploy credentials (VERCEL_*, FIREBASE_*, ...) never reach the app pod.
  const podSecrets = context.required_secrets.filter((s) => !isDeploymentSecret(s));
  const imageTag = policy.imageTag ?? 'latest';

  const envFromLines: string[] = [];
  if (Object.keys(context.env_vars).length > 0 || podSecrets.length > 0) {
    envFromLines.push('          envFrom:');
    if (Object.keys(context.env_vars).length > 0) {
      envFromLines.push(`            - configMapRef:\n                name: ${appName}-config`);
    }
    if (podSecrets.length > 0) {
      envFromLines.push(
        `            - secretRef:\n                name: ${appName}-secrets\n                optional: true`
      );
    }
  }

  const HTTP_PROBE_PATHS: Record<string, string> = {
    Streamlit: '/_stcore/health',
    FastAPI: '/health',
    'Next.js': '/',
  };
  const probePath = primary?.framework ? HTTP_PROBE_PATHS[primary.framework] : undefined;
  const probe = (name: string, delay: number) =>
    probePath
      ? `          ${name}:\n            httpGet:\n              path: ${probePath}\n              port: ${port}\n            initialDelaySeconds: ${delay}\n            periodSeconds: 10`
      : `          ${name}:\n            tcpSocket:\n              port: ${port}\n            initialDelaySeconds: ${delay}\n            periodSeconds: 10`;

  const deployment = [
    '# Synthesized deterministically by Heurix (hx)',
    'apiVersion: apps/v1',
    'kind: Deployment',
    'metadata:',
    `  name: ${appName}`,
    '  labels:',
    `    app: ${appName}`,
    'spec:',
    '  replicas: 2',
    '  selector:',
    '    matchLabels:',
    `      app: ${appName}`,
    '  template:',
    '    metadata:',
    '      labels:',
    `        app: ${appName}`,
    '    spec:',
    '      securityContext:',
    '        runAsNonRoot: true',
    '        seccompProfile:',
    '          type: RuntimeDefault',
    '      containers:',
    `        - name: ${appName}`,
    `          image: ${appName}:${imageTag}`,
    '          securityContext:',
    '            allowPrivilegeEscalation: false',
    '            readOnlyRootFilesystem: true',
    '            capabilities:',
    '              drop:',
    '                - ALL',
    '          ports:',
    `            - containerPort: ${port}`,
    '          resources:',
    '            requests:',
    `              cpu: ${cpuReq}`,
    `              memory: ${memReq}`,
    '            limits:',
    '              cpu: 500m',
    `              memory: ${memLimit}`,
    probe('livenessProbe', 15),
    probe('readinessProbe', 5),
    ...envFromLines,
    '',
  ].join('\n');

  const service = [
    '# Synthesized deterministically by Heurix (hx)',
    'apiVersion: v1',
    'kind: Service',
    'metadata:',
    `  name: ${appName}-service`,
    '  labels:',
    `    app: ${appName}`,
    'spec:',
    '  type: ClusterIP',
    '  selector:',
    `    app: ${appName}`,
    '  ports:',
    '    - protocol: TCP',
    '      port: 80',
    `      targetPort: ${port}`,
    '',
  ].join('\n');

  const ingress = [
    '# Synthesized deterministically by Heurix (hx)',
    'apiVersion: networking.k8s.io/v1',
    'kind: Ingress',
    'metadata:',
    `  name: ${appName}-ingress`,
    'spec:',
    '  ingressClassName: nginx',
    '  rules:',
    '    - http:',
    '        paths:',
    '          - path: /',
    '            pathType: Prefix',
    '            backend:',
    '              service:',
    `                name: ${appName}-service`,
    '                port:',
    '                  number: 80',
    '',
  ].join('\n');

  const kindConfig = [
    '# Synthesized deterministically by Heurix (hx)',
    'kind: Cluster',
    'apiVersion: kind.x-k8s.io/v1alpha4',
    'metadata:',
    `  name: ${appName}-cluster`,
    'nodes:',
    '  - role: control-plane',
    '    kubeadmConfigPatches:',
    '      - |',
    '        kind: InitConfiguration',
    '        nodeRegistration:',
    '          kubeletExtraArgs:',
    '            node-labels: "ingress-ready=true"',
    '    extraPortMappings:',
    '      - containerPort: 80',
    '        hostPort: 80',
    '        protocol: TCP',
    '      - containerPort: 443',
    '        hostPort: 443',
    '        protocol: TCP',
    '',
  ].join('\n');

  const k8sOutputs: Record<string, string> = {
    'k8s/deployment.yaml': deployment,
    'k8s/service.yaml': service,
    'k8s/ingress.yaml': ingress,
    'k8s/kind-config.yaml': kindConfig,
  };

  if (Object.keys(context.env_vars).length > 0) {
    const cmLines = [
      '# Synthesized deterministically by Heurix (hx)',
      'apiVersion: v1',
      'kind: ConfigMap',
      'metadata:',
      `  name: ${appName}-config`,
      '  labels:',
      `    app: ${appName}`,
      'data:',
      ...Object.entries(context.env_vars).map(([k, v]) => `  ${k}: ${JSON.stringify(v)}`),
      '',
    ];
    k8sOutputs['k8s/configmap.yaml'] = cmLines.join('\n');
  }

  if (podSecrets.length > 0) {
    k8sOutputs['k8s/secret.yaml'] = [
      '# Synthesized deterministically by Heurix (hx)',
      'apiVersion: v1',
      'kind: Secret',
      'metadata:',
      `  name: ${appName}-secrets`,
      '  labels:',
      `    app: ${appName}`,
      'type: Opaque',
      'stringData:',
      ...[...podSecrets].sort().map((k) => `  ${k}: "CHANGE_ME"`),
      '',
    ].join('\n');
  }

  return k8sOutputs;
}

export function runHeurixScan(repoName: string, files: VirtualFile[]): ScanResult {
  const start = performance.now();
  const indexer = new VirtualRepoIndexer(files);
  const policy = loadPolicy(indexer);

  const context: ProjectContext = {
    repo_name: repoName,
    repo_root: `/workspace/${repoName}`,
    is_monorepo: false,
    monorepo_packages: [],
    languages: [],
    services: [],
    containers: [],
    deployment_targets: [],
    required_secrets: [],
    env_vars: {},
    explain_log: [`Scanning repository at /workspace/${repoName} (indexed ${indexer.files.length} files)...`],
    confidence: 1.0,
    runner: policy.runner ?? 'ubuntu-latest',
  };

  if (policy.error) {
    context.explain_log.push(`Warning: Invalid Policy: .heurix.toml could not be parsed (${policy.error}); using defaults`);
  } else if (policy.source) {
    const notes: string[] = [];
    if (policy.runner) notes.push(`runner=${policy.runner}`);
    if (policy.paths) notes.push(`paths=[${policy.paths.join(', ')}]`);
    if (policy.pathsIgnore.length) notes.push(`paths_ignore=[${policy.pathsIgnore.join(', ')}]`);
    if (policy.includeK8s !== null) notes.push(`include_k8s=${policy.includeK8s}`);
    if (!policy.includeDependabot) notes.push('include_dependabot=false');
    for (const [k, v] of Object.entries(policy.overrides)) notes.push(`${k}=${v}`);
    context.explain_log.push(`Loaded policy .heurix.toml${notes.length ? ` (${notes.join(', ')})` : ''}`);
  }

  detectPython(indexer, context);
  detectNode(indexer, context);
  detectRust(indexer, context);
  detectGo(indexer, context);
  detectCpp(indexer, context);
  detectDocker(indexer, context);
  detectEnv(indexer, context);
  detectCloud(indexer, context);

  // [overrides] pin runtimes explicitly (python = "3.12", node = "20.x", ...)
  for (const lang of context.languages) {
    const pinned = policy.overrides[lang.language];
    if (pinned && pinned !== lang.runtime_version) {
      lang.runtime_version = pinned;
      lang.version_source = '.heurix.toml [overrides]';
      context.explain_log.push(`Policy override: ${lang.language} runtime pinned to ${pinned}`);
    }
  }

  if (context.containers.length === 0 && policy.includeK8s !== true && context.languages.length > 0) {
    context.explain_log.push('Skipping Kubernetes manifests: no Dockerfile (repo is not containerized)');
  }

  const synthesized: Record<string, string> = {};
  if (context.languages.length > 0 || context.deployment_targets.length > 0) {
    synthesized['.github/workflows/ci.yml'] = synthesizeGitHubActions(context, policy);
    if (policy.includeDependabot) {
      synthesized['.github/dependabot.yml'] = synthesizeDependabot(context);
    }
  }

  Object.assign(synthesized, synthesizeKubernetes(context, policy));

  const durationMs = Math.max(0.2, Number((performance.now() - start).toFixed(2)));
  return { context, policy, synthesized, durationMs };
}

export interface MergeSimulation {
  merged: string;
  /** Human-readable notes for hand-edited values the merge replaces (as `hx generate` prints). */
  replaced: string[];
  /** Keys kept because their line ends with `# @heurix:preserve`. */
  keptKeys: string[];
}

const PRESERVE_RE = /#\s*@(heurix|autoyaml):preserve/;
const KEY_LEVEL_PRESERVE = ['runs-on', 'services', 'needs', 'strategy'];

function stepRunsByName(yaml: string): Map<string, string> {
  const out = new Map<string, string>();
  const lines = yaml.split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    const name = lines[i].match(/^\s*-\s+name:\s*(.+)$/);
    if (!name) continue;
    for (let j = i + 1; j < lines.length && !/^\s*-\s/.test(lines[j]); j += 1) {
      const run = lines[j].match(/^\s+run:\s*(.+)$/);
      if (run) {
        out.set(name[1].trim(), run[1].trim());
        break;
      }
    }
  }
  return out;
}

export function simulateSmartMerge(existingCi: string, newCi: string): MergeSimulation {
  const lines = existingCi.split('\n');
  const preservedBlocks: string[] = [];
  const keptKeys: string[] = [];
  const replaced: string[] = [];
  let i = 0;

  // Key-level preserve: `runs-on: self-hosted  # @heurix:preserve` keeps the value.
  const keptJobKeys = new Map<string, string>();
  for (const line of lines) {
    const m = line.match(/^    ([a-z-]+):(.*)$/);
    if (m && KEY_LEVEL_PRESERVE.includes(m[1]) && PRESERVE_RE.test(line)) {
      keptJobKeys.set(m[1], line);
      keptKeys.push(`jobs.test.${m[1]}`);
    }
  }

  while (i < lines.length) {
    const line = lines[i];
    if (PRESERVE_RE.test(line) && line.trim().startsWith('#')) {
      const indent = line.match(/^\s*/)?.[0] ?? '';
      const block = [line];
      if (i + 1 < lines.length && lines[i + 1].trim().startsWith('- name:')) {
        i += 1;
        block.push(lines[i]);
        while (i + 1 < lines.length && lines[i + 1].startsWith(`${indent}  `) && !lines[i + 1].trim().startsWith('- ')) {
          i += 1;
          block.push(lines[i]);
        }
      }
      preservedBlocks.push(block.join('\n'));
    }
    i += 1;
  }

  // Replacement notices: managed values that were hand-edited
  const oldRunsOn = existingCi.match(/^  test:\n(?:.*\n)*?    runs-on:\s*([^#\n]+)/m)?.[1]?.trim();
  const newRunsOn = newCi.match(/^  test:\n(?:.*\n)*?    runs-on:\s*([^#\n]+)/m)?.[1]?.trim();
  if (oldRunsOn && newRunsOn && oldRunsOn !== newRunsOn && !keptJobKeys.has('runs-on')) {
    replaced.push(`jobs.test.runs-on: '${oldRunsOn}' -> '${newRunsOn}'`);
  }
  const oldRuns = stepRunsByName(existingCi);
  for (const [name, newRun] of stepRunsByName(newCi)) {
    const oldRun = oldRuns.get(name);
    if (oldRun && oldRun !== newRun) {
      replaced.push(`jobs.test.steps['${name}'].run: '${oldRun}' -> '${newRun}'`);
    }
  }

  // Also preserve custom jobs not managed by Heurix (anything except test / deploy_*)
  const customJobs: string[] = [];
  const jobsIdx = lines.findIndex((l) => /^jobs:\s*$/.test(l));
  if (jobsIdx !== -1) {
    for (let j = jobsIdx + 1; j < lines.length; j += 1) {
      const job = lines[j].match(/^  ([a-zA-Z0-9_-]+):\s*$/);
      if (!job || job[1] === 'test' || job[1].startsWith('deploy_')) continue;
      const collected = [lines[j]];
      while (j + 1 < lines.length && !/^  [a-zA-Z0-9_-]+:/.test(lines[j + 1]) && !/^\S/.test(lines[j + 1])) {
        j += 1;
        collected.push(lines[j]);
      }
      customJobs.push(collected.join('\n').trimEnd());
    }
  }

  let merged = newCi.trimEnd();
  for (const [key, original] of keptJobKeys) {
    merged = merged.replace(new RegExp(`^    ${key}:.*$`, 'm'), original);
  }
  if (preservedBlocks.length > 0) {
    // Inject preserved steps at the end of the test job, before any deploy jobs
    const deployIdx = merged.search(/\n  deploy_(vercel|firebase):/);
    const blockText = '\n' + preservedBlocks.join('\n');
    merged = deployIdx !== -1 ? merged.slice(0, deployIdx) + blockText + merged.slice(deployIdx) : merged + blockText;
  }
  for (const job of customJobs) {
    merged += '\n' + job;
  }

  return { merged: merged + '\n', replaced, keptKeys };
}

/** Find services in one job that bind the same host port (mirrors core/drift.py). */
export function findServicePortCollisions(workflow: string): { job: string; port: string; services: string[] }[] {
  const out: { job: string; port: string; services: string[] }[] = [];
  const lines = workflow.split('\n');
  let job: string | null = null;
  let inServices = false;
  let svc: string | null = null;
  let byPort = new Map<string, string[]>();
  const flush = () => {
    if (job) {
      for (const [port, names] of byPort) if (names.length > 1) out.push({ job, port, services: names });
    }
    byPort = new Map();
  };
  for (const line of lines) {
    const jobM = line.match(/^  ([a-zA-Z0-9_-]+):\s*$/);
    if (jobM) {
      flush();
      job = jobM[1];
      inServices = false;
      continue;
    }
    if (/^    services:\s*$/.test(line)) {
      inServices = true;
      continue;
    }
    if (/^    \S/.test(line)) inServices = false;
    if (!inServices) continue;
    const svcM = line.match(/^      ([a-zA-Z0-9_-]+):\s*$/);
    if (svcM) {
      svc = svcM[1];
      continue;
    }
    const portM = line.match(/^\s+-\s*['"]?([\d.:]+)['"]?\s*$/);
    if (svc && portM) {
      const parts = portM[1].split(':');
      if (parts.length >= 2) {
        const host = parts[parts.length - 2];
        const names = byPort.get(host) ?? [];
        if (!names.includes(svc)) names.push(svc);
        byPort.set(host, names);
      }
    }
  }
  flush();
  return out;
}

export function checkDrift(
  context: ProjectContext,
  existingCi: string | null,
  policy?: HeurixPolicy
): DriftFinding[] {
  const findings: DriftFinding[] = [];
  const ciPath = '.github/workflows/ci.yml';

  if (policy?.error) {
    findings.push({
      file_path: '.heurix.toml',
      issue: `Invalid Policy: ${policy.error}`,
      severity: 'ERROR',
      recommendation: 'Fix the .heurix.toml syntax; hx check exits 1 until the policy parses.',
    });
  }

  if (!existingCi) {
    findings.push({
      file_path: ciPath,
      issue: 'File does not exist in repository.',
      severity: 'WARNING',
      recommendation: `Run 'hx generate' to synthesize ${ciPath}.`,
    });
    return findings;
  }

  // Services sharing a host port cannot all start, so the job fails before any step runs
  for (const c of findServicePortCollisions(existingCi)) {
    findings.push({
      file_path: ciPath,
      issue: `Job '${c.job}': services ${c.services.map((n) => `'${n}'`).join(', ')} all bind host port ${c.port}; only one can start, so the job will fail.`,
      severity: 'ERROR',
      recommendation: "Run 'hx generate' to merge duplicate services, or remove the extra service.",
    });
  }

  for (const svc of context.services) {
    if (!existingCi.toLowerCase().includes(`${svc.name.toLowerCase()}:`)) {
      findings.push({
        file_path: ciPath,
        issue: `Service '${svc.name}' is required by codebase dependencies (${svc.source_file}) but missing from workflow.`,
        severity: 'WARNING',
        recommendation: `Run 'hx generate' to inject service '${svc.name}'.`,
      });
    }
  }

  for (const lang of context.languages) {
    if (lang.runtime_version !== 'latest' && !existingCi.includes(lang.runtime_version)) {
      findings.push({
        file_path: ciPath,
        issue: `Runtime version mismatch: codebase specifies ${lang.language} ${lang.runtime_version} (${lang.version_source}), not found in workflow.`,
        severity: 'WARNING',
        recommendation: `Run 'hx generate' to update ${lang.language} version.`,
      });
    }
    if (lang.package_manager === 'uv' && !existingCi.includes('setup-uv')) {
      findings.push({
        file_path: ciPath,
        issue: 'uv package manager detected in codebase (uv.lock), but workflow does not use astral-sh/setup-uv.',
        severity: 'WARNING',
        recommendation: "Run 'hx generate' to optimize workflow for uv.",
      });
    }
  }

  return findings;
}
