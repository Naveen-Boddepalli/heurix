import { useMemo, useRef, useState } from 'react';
import {
  downloadZipArchive,
  formatAllConfigsText,
  generateSetupShellScript,
} from '../engine/exportArchive';
import { checkDrift, runHeurixScan, simulateSmartMerge } from '../engine/heuristics';
import { PRESET_REPOS, STARTER_FILE_TEMPLATES } from '../engine/presets';
import type { VirtualFile } from '../engine/types';
import { CodeBlock } from './CodeBlock';

type OutputTab = 'generate' | 'scan' | 'merge' | 'drift';

const OUTPUT_TABS: { id: OutputTab; label: string }[] = [
  { id: 'generate', label: 'hx generate (YAML)' },
  { id: 'scan', label: 'hx scan (IR JSON)' },
  { id: 'merge', label: 'hx diff (# @heurix:preserve)' },
  { id: 'drift', label: 'hx check (Drift Guard)' },
];

export function Playground() {
  const [presetId, setPresetId] = useState(PRESET_REPOS[0].id);
  const currentPreset = PRESET_REPOS.find((p) => p.id === presetId) ?? PRESET_REPOS[0];

  const [files, setFiles] = useState<VirtualFile[]>(() =>
    currentPreset.files.map((f) => ({ ...f }))
  );
  const [selectedFilePath, setSelectedFilePath] = useState<string>(
    currentPreset.files[0]?.path ?? ''
  );
  const [activeTab, setActiveTab] = useState<OutputTab>('generate');
  const [selectedOutputFile, setSelectedOutputFile] = useState<string>('.github/workflows/ci.yml');
  const [simulatedCi, setSimulatedCi] = useState<string | null>(null);
  const [driftNotice, setDriftNotice] = useState<string | null>(null);
  const [showWorkflowYaml, setShowWorkflowYaml] = useState(false);

  // Add File state
  const [isAddingFile, setIsAddingFile] = useState(false);
  const [newFilePath, setNewFilePath] = useState(STARTER_FILE_TEMPLATES[1].defaultPath);
  const [templateIdx, setTemplateIdx] = useState(1);

  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function selectPreset(id: string) {
    const next = PRESET_REPOS.find((p) => p.id === id) ?? PRESET_REPOS[0];
    setPresetId(next.id);
    setFiles(next.files.map((f) => ({ ...f })));
    setSelectedFilePath(next.files[0]?.path ?? '');
    setSelectedOutputFile('.github/workflows/ci.yml');
    setIsAddingFile(false);
    setSimulatedCi(null);
    setDriftNotice(null);
  }

  function toggleFile(path: string) {
    setFiles((prev) =>
      prev.map((f) => (f.path === path ? { ...f, enabled: !f.enabled } : f))
    );
  }

  function updateFileContent(path: string, content: string) {
    setFiles((prev) =>
      prev.map((f) => (f.path === path ? { ...f, content } : f))
    );
  }

  function handleCreateFile(e: React.FormEvent) {
    e.preventDefault();
    const cleanPath = newFilePath.trim();
    if (!cleanPath) return;

    if (files.some((f) => f.path === cleanPath)) {
      alert(`File "${cleanPath}" already exists.`);
      return;
    }

    const tpl = STARTER_FILE_TEMPLATES[templateIdx] ?? STARTER_FILE_TEMPLATES[0];
    const newFile: VirtualFile = {
      path: cleanPath,
      enabled: true,
      content: tpl.content,
    };

    setFiles((prev) => [...prev, newFile]);
    setSelectedFilePath(cleanPath);
    setIsAddingFile(false);
  }

  function handleDeleteFile(path: string) {
    setFiles((prev) => {
      const next = prev.filter((f) => f.path !== path);
      if (selectedFilePath === path && next.length > 0) {
        setSelectedFilePath(next[0].path);
      }
      return next;
    });
  }

  const [copiedAll, setCopiedAll] = useState(false);

  function handleCopyAll() {
    const exportable = outputKeys.map((p) => ({ path: p, content: scanResult.synthesized[p] }));
    const text = formatAllConfigsText(exportable);
    navigator.clipboard.writeText(text).then(() => {
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2000);
    });
  }

  function handleDownloadZip() {
    const exportable = outputKeys.map((p) => ({ path: p, content: scanResult.synthesized[p] }));
    downloadZipArchive(`${currentPreset.id}-heurix-configs`, exportable);
  }

  function handleDownloadScript() {
    const exportable = outputKeys.map((p) => ({ path: p, content: scanResult.synthesized[p] }));
    const script = generateSetupShellScript(exportable);
    const blob = new Blob([script], { type: 'text/x-shellscript;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `apply-${currentPreset.id}-configs.sh`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  const scanResult = useMemo(
    () => runHeurixScan(currentPreset.repoName, files),
    [currentPreset.repoName, files]
  );

  const outputKeys = Object.keys(scanResult.synthesized);
  const activeOutputPath = outputKeys.includes(selectedOutputFile)
    ? selectedOutputFile
    : outputKeys[0] ?? '';
  const activeOutputCode = activeOutputPath
    ? scanResult.synthesized[activeOutputPath]
    : '# Enable at least one language or deployment config file to synthesize YAML.';

  const activeFile = files.find((f) => f.path === selectedFilePath) ?? files[0];

  const existingCiSample =
    currentPreset.existingCiForMerge ??
    `name: CI\non:\n  push:\n    branches: [main]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      # @heurix:preserve\n      - name: Custom security & SBOM upload\n        run: ./scripts/upload-sbom.sh\n  slack_notify:\n    needs: test\n    if: failure()\n    runs-on: ubuntu-latest\n    steps:\n      - uses: slackapi/slack-github-action@v1`;

  const mergedCiOutput = useMemo(
    () =>
      simulateSmartMerge(
        existingCiSample,
        scanResult.synthesized['.github/workflows/ci.yml'] ?? ''
      ),
    [existingCiSample, scanResult.synthesized]
  );

  const staleBaselineCi = useMemo(() => {
    return `name: CI\non:\n  push:\n    branches: [main]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - name: Legacy test\n        run: echo "Outdated workflow missing detected services and runtimes"`;
  }, []);

  const activeCheckedWorkflow = simulatedCi ?? staleBaselineCi;

  const driftFindings = useMemo(() => {
    return checkDrift(scanResult.context, activeCheckedWorkflow);
  }, [scanResult.context, activeCheckedWorkflow]);

  const cliCheckOutput = useMemo(() => {
    if (driftFindings.length === 0) {
      return `$ hx check\n✔ Zero Drift Detected: CI/CD workflows are completely synchronized with the codebase!\n\nExit code: 0 (PASS)`;
    }
    const lines = [
      `$ hx check`,
      `⚠️ Drift Detected (${driftFindings.length} issue(s)):`,
      '',
    ];
    for (const f of driftFindings) {
      lines.push(`[${f.severity}] ${f.file_path}: ${f.issue}`);
      lines.push(`  ↳ Recommendation: ${f.recommendation}`);
      lines.push('');
    }
    lines.push(`Error: Process completed with exit code 1.`);
    return lines.join('\n');
  }, [driftFindings]);

  function handleInjectRedis() {
    setFiles((prev) => {
      if (prev.some((f) => f.path === 'pyproject.toml')) {
        return prev.map((f) => {
          if (f.path === 'pyproject.toml' && !f.content.includes('redis')) {
            const updated = f.content.replace(
              /dependencies\s*=\s*\[/,
              'dependencies = [\n    "redis>=5.0.0",'
            );
            return { ...f, content: updated, enabled: true };
          }
          return f;
        });
      }
      if (prev.some((f) => f.path === 'package.json')) {
        return prev.map((f) => {
          if (f.path === 'package.json' && !f.content.includes('redis')) {
            const updated = f.content.replace(
              /"dependencies":\s*\{/,
              '"dependencies": {\n    "redis": "^4.6.0",'
            );
            return { ...f, content: updated, enabled: true };
          }
          return f;
        });
      }
      const compose = prev.find((f) => f.path === 'docker-compose.yml');
      if (compose) {
        if (!compose.content.includes('redis')) {
          return prev.map((f) =>
            f.path === 'docker-compose.yml'
              ? { ...f, content: `${f.content.trimEnd()}\n  redis:\n    image: redis:7-alpine\n    ports:\n      - "6379:6379"\n`, enabled: true }
              : f
          );
        }
        return prev;
      }
      return [
        ...prev,
        {
          path: 'docker-compose.yml',
          enabled: true,
          content: 'services:\n  redis:\n    image: redis:7-alpine\n    ports:\n      - "6379:6379"\n',
        },
      ];
    });
    setDriftNotice('⚡ Injected Redis into codebase dependencies. Workflow is missing Redis service!');
  }

  function handleBumpRuntime() {
    setFiles((prev) => {
      if (prev.some((f) => f.path === '.python-version' || f.path === 'pyproject.toml')) {
        const hasVersionFile = prev.some((f) => f.path === '.python-version');
        if (hasVersionFile) {
          return prev.map((f) => (f.path === '.python-version' ? { ...f, content: '3.13\n', enabled: true } : f));
        }
        return [...prev, { path: '.python-version', enabled: true, content: '3.13\n' }];
      }
      if (prev.some((f) => f.path === '.nvmrc' || f.path === 'package.json')) {
        const hasNvm = prev.some((f) => f.path === '.nvmrc');
        if (hasNvm) {
          return prev.map((f) => (f.path === '.nvmrc' ? { ...f, content: '22\n', enabled: true } : f));
        }
        return [...prev, { path: '.nvmrc', enabled: true, content: '22\n' }];
      }
      return [...prev, { path: '.python-version', enabled: true, content: '3.13\n' }];
    });
    setDriftNotice('⚡ Bumped runtime version in codebase. Workflow does not match new runtime requirement!');
  }

  function handleInjectUv() {
    setFiles((prev) => {
      if (prev.some((f) => f.path === 'uv.lock')) return prev;
      return [...prev, { path: 'uv.lock', enabled: true, content: '# uv lockfile v1\nversion = 1\n' }];
    });
    setDriftNotice('⚡ Added uv.lock! Heurix detected uv, but workflow does not use setup-uv.');
  }

  function handleInjectPostgres() {
    setFiles((prev) => {
      const compose = prev.find((f) => f.path === 'docker-compose.yml');
      if (compose) {
        if (!compose.content.includes('postgres')) {
          return prev.map((f) =>
            f.path === 'docker-compose.yml'
              ? { ...f, content: `${f.content.trimEnd()}\n  postgres:\n    image: postgres:16-alpine\n    ports:\n      - "5432:5432"\n`, enabled: true }
              : f
          );
        }
        return prev;
      }
      return [
        ...prev,
        {
          path: 'docker-compose.yml',
          enabled: true,
          content: 'services:\n  postgres:\n    image: postgres:16-alpine\n    ports:\n      - "5432:5432"\n',
        },
      ];
    });
    setDriftNotice('⚡ Injected PostgreSQL service requirement. Workflow is missing postgres container!');
  }

  function handleReconcile() {
    const currentGenerated = scanResult.synthesized['.github/workflows/ci.yml'];
    if (currentGenerated) {
      setSimulatedCi(currentGenerated);
      setDriftNotice('✔ Reconciled! Ran simulated hx generate — workflow now matches all codebase requirements.');
    }
  }

  function handleResetStale() {
    setSimulatedCi(staleBaselineCi);
    setDriftNotice('Reset workflow to stale baseline (Exit code 1).');
  }

  function handleTabKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = -1;
    if (e.key === 'ArrowRight') next = (index + 1) % OUTPUT_TABS.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + OUTPUT_TABS.length) % OUTPUT_TABS.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = OUTPUT_TABS.length - 1;

    if (next !== -1) {
      e.preventDefault();
      setActiveTab(OUTPUT_TABS[next].id);
      tabRefs.current[next]?.focus();
    }
  }

  return (
    <section id="playground" className="section">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">Interactive Playground</span>
          <h2>Run the deterministic engine live in your browser</h2>
          <p>
            Select a preset repository or edit any manifest file on the left. Heurix re-scans your virtual codebase
            on every keystroke with zero network calls and synthesizes schema-validated YAML outputs.
          </p>
        </div>

        <div className="playground-shell">
          <div className="preset-strip" role="group" aria-label="Sample repositories">
            {PRESET_REPOS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="preset-btn"
                aria-pressed={preset.id === presetId}
                onClick={() => selectPreset(preset.id)}
              >
                {preset.label}
              </button>
            ))}

            <div className="scan-meta" aria-live="polite">
              <span>✔ Scanned in {scanResult.durationMs} ms</span>
              <span>•</span>
              <span>{outputKeys.length} artifacts</span>
            </div>
          </div>

          <div className="workbench-grid">
            {/* Left Sidebar: Virtual Repo Explorer & Live File Editor */}
            <aside className="workbench-sidebar" aria-label="Repository files editor">
              <div
                style={{
                  padding: '0.75rem 1rem',
                  borderBlockEnd: '1px solid var(--border-subtle)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '0.5rem',
                }}
              >
                <div>
                  <div style={{ fontWeight: 700, fontSize: '0.9375rem' }}>
                    {currentPreset.repoName}/
                  </div>
                  <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                    {currentPreset.subtitle}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <button
                    type="button"
                    className="code-copy-btn"
                    onClick={() => setIsAddingFile((prev) => !prev)}
                    aria-expanded={isAddingFile}
                  >
                    {isAddingFile ? 'Cancel' : '+ File'}
                  </button>
                  <button
                    type="button"
                    className="code-copy-btn"
                    onClick={() => selectPreset(currentPreset.id)}
                  >
                    Reset
                  </button>
                </div>
              </div>

              {isAddingFile && (
                <form className="add-file-box" onSubmit={handleCreateFile}>
                  <label htmlFor="starter-template-select" style={{ fontSize: '0.75rem', fontWeight: 600 }}>
                    Choose template:
                  </label>
                  <select
                    id="starter-template-select"
                    className="form-select"
                    value={templateIdx}
                    onChange={(e) => {
                      const idx = Number(e.target.value);
                      setTemplateIdx(idx);
                      const tpl = STARTER_FILE_TEMPLATES[idx];
                      if (tpl) setNewFilePath(tpl.defaultPath);
                    }}
                  >
                    {STARTER_FILE_TEMPLATES.map((tpl, i) => (
                      <option key={tpl.name} value={i}>
                        {tpl.name} ({tpl.defaultPath})
                      </option>
                    ))}
                  </select>

                  <label htmlFor="custom-file-path-input" style={{ fontSize: '0.75rem', fontWeight: 600 }}>
                    File path:
                  </label>
                  <div style={{ display: 'flex', gap: '0.35rem' }}>
                    <input
                      id="custom-file-path-input"
                      type="text"
                      className="form-input"
                      value={newFilePath}
                      onChange={(e) => setNewFilePath(e.target.value)}
                      placeholder="e.g. Dockerfile"
                      required
                    />
                    <button type="submit" className="btn btn-primary" style={{ minBlockSize: '2.25rem', paddingInline: '0.75rem', fontSize: '0.8125rem' }}>
                      Add
                    </button>
                  </div>
                </form>
              )}

              <ul className="file-tree" aria-label="Repository files">
                {files.map((file) => (
                  <li key={file.path} className="file-row">
                    <input
                      type="checkbox"
                      className="file-toggle"
                      checked={file.enabled}
                      onChange={() => toggleFile(file.path)}
                      aria-label={`Include ${file.path} in scan`}
                    />
                    <button
                      type="button"
                      className={`file-select-btn${!file.enabled ? ' is-disabled' : ''}`}
                      aria-current={activeFile?.path === file.path ? 'true' : undefined}
                      onClick={() => setSelectedFilePath(file.path)}
                    >
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {file.path}
                      </span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                        {file.enabled ? 'edit' : 'off'}
                      </span>
                    </button>
                    {files.length > 1 && (
                      <button
                        type="button"
                        className="file-del-btn"
                        onClick={() => handleDeleteFile(file.path)}
                        aria-label={`Delete ${file.path}`}
                        title={`Delete ${file.path}`}
                      >
                        ×
                      </button>
                    )}
                  </li>
                ))}
              </ul>

              {activeFile && (
                <div className="file-editor-wrap">
                  <label htmlFor="virtual-file-editor" className="file-editor-label">
                    <span>Editing: {activeFile.path}</span>
                    <span>Live heuristic input</span>
                  </label>
                  <textarea
                    id="virtual-file-editor"
                    className="file-editor"
                    value={activeFile.content}
                    onChange={(e) => updateFileContent(activeFile.path, e.target.value)}
                    spellCheck={false}
                  />
                </div>
              )}
            </aside>

            {/* Right Panel: Synthesized Results & Explainability */}
            <div className="workbench-main">
              <div role="tablist" aria-label="Heurix output views" className="tablist">
                {OUTPUT_TABS.map((tab, idx) => (
                  <button
                    key={tab.id}
                    ref={(el) => {
                      tabRefs.current[idx] = el;
                    }}
                    type="button"
                    role="tab"
                    id={`output-tab-${tab.id}`}
                    aria-selected={activeTab === tab.id}
                    tabIndex={activeTab === tab.id ? 0 : -1}
                    className="tab-btn"
                    onClick={() => setActiveTab(tab.id)}
                    onKeyDown={(e) => handleTabKeyDown(e, idx)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Tab 1: hx generate */}
              <div
                role="tabpanel"
                aria-labelledby="output-tab-generate"
                hidden={activeTab !== 'generate'}
                tabIndex={activeTab === 'generate' ? 0 : undefined}
              >
                <div className="output-body">
                  <div className="explain-box">
                    <div className="explain-title">
                      🔍 Heuristic Reasoning Tree (`hx generate --explain`)
                    </div>
                    <ul className="explain-list">
                      {scanResult.context.explain_log.map((step, i) => (
                        <li key={i}>
                          <span className="explain-check" aria-hidden="true">
                            ✔
                          </span>
                          <span>{step}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {outputKeys.length > 0 && (
                    <div className="export-actions-bar">
                      <div className="output-file-bar" role="group" aria-label="Synthesized YAML targets">
                        {outputKeys.map((filePath) => {
                          const lineCount = scanResult.synthesized[filePath].trim().split('\n').length;
                          return (
                            <button
                              key={filePath}
                              type="button"
                              className="output-file-pill"
                              aria-pressed={activeOutputPath === filePath}
                              onClick={() => setSelectedOutputFile(filePath)}
                            >
                              {filePath} ({lineCount}L)
                            </button>
                          );
                        })}
                      </div>

                      <div className="export-btn-group" role="group" aria-label="Export configurations">
                        <button
                          type="button"
                          className="export-btn"
                          onClick={handleDownloadZip}
                          title="Download all synthesized configurations in a ZIP archive"
                        >
                          <span aria-hidden="true">📦</span> Download ZIP
                        </button>
                        <button
                          type="button"
                          className="export-btn"
                          onClick={handleDownloadScript}
                          title="Download bash setup script"
                        >
                          <span aria-hidden="true">⚡</span> Setup Script
                        </button>
                        <button
                          type="button"
                          className={`export-btn${copiedAll ? ' is-success' : ''}`}
                          onClick={handleCopyAll}
                          title="Copy all synthesized YAML configurations"
                        >
                          <span aria-hidden="true">{copiedAll ? '✔' : '📋'}</span>
                          {copiedAll ? 'Copied All!' : 'Copy All YAML'}
                        </button>
                      </div>
                    </div>
                  )}

                  <CodeBlock
                    title={activeOutputPath || 'No targets generated'}
                    code={activeOutputCode}
                    badge={outputKeys.length > 0 ? '✔ JSON Schema Validated' : undefined}
                  />
                </div>
              </div>

              {/* Tab 2: hx scan */}
              <div
                role="tabpanel"
                aria-labelledby="output-tab-scan"
                hidden={activeTab !== 'scan'}
                tabIndex={activeTab === 'scan' ? 0 : undefined}
              >
                <div className="output-body">
                  <p style={{ fontSize: '0.9375rem' }}>
                    Generators never touch the filesystem directly—all 8 detectors populate this strongly-typed
                    <code>ProjectContext</code> Pydantic IR.
                  </p>
                  <CodeBlock
                    title="hx scan (ProjectContext IR)"
                    code={JSON.stringify(scanResult.context, null, 2)}
                    badge={`Confidence: ${Math.round(scanResult.context.confidence * 100)}%`}
                  />
                </div>
              </div>

              {/* Tab 3: Smart Merge */}
              <div
                role="tabpanel"
                aria-labelledby="output-tab-merge"
                hidden={activeTab !== 'merge'}
                tabIndex={activeTab === 'merge' ? 0 : undefined}
              >
                <div className="output-body">
                  <p style={{ fontSize: '0.9375rem' }}>
                    <code>SmartMerger</code> parses existing YAML via <code>ruamel.yaml</code> AST round-tripping.
                    Custom jobs (like <code>slack_notify</code>) and any step marked with{' '}
                    <code># @heurix:preserve</code> survive regeneration intact while managed steps update.
                  </p>
                  <div style={{ display: 'grid', gap: '1rem' }}>
                    <CodeBlock
                      title="Before: Existing .github/workflows/ci.yml (with custom steps)"
                      code={existingCiSample}
                      highlightDiff
                    />
                    <CodeBlock
                      title="After: Merged .github/workflows/ci.yml (AST preserved)"
                      code={mergedCiOutput}
                      badge="✔ Preserved user customizations"
                      highlightDiff
                    />
                  </div>
                </div>
              </div>

              {/* Tab 4: Drift Guard */}
              <div
                role="tabpanel"
                aria-labelledby="output-tab-drift"
                hidden={activeTab !== 'drift'}
                tabIndex={activeTab === 'drift' ? 0 : undefined}
              >
                <div className="output-body">
                  {driftNotice && (
                    <div className="drift-notice">
                      <span aria-hidden="true">💡</span>
                      <span>{driftNotice}</span>
                    </div>
                  )}

                  <div className="drift-scenarios-bar">
                    <div className="drift-scenario-group" role="group" aria-label="Inject drift scenarios">
                      <span style={{ fontSize: '0.78125rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                        Inject Drift:
                      </span>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleInjectRedis}
                        title="Add Redis dependency to codebase manifest"
                      >
                        + Redis Dependency
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleBumpRuntime}
                        title="Bump runtime version in codebase"
                      >
                        + Bump Runtime
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleInjectUv}
                        title="Add uv.lock package manager file"
                      >
                        + uv Package Manager
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleInjectPostgres}
                        title="Add PostgreSQL container in compose"
                      >
                        + Postgres Service
                      </button>
                    </div>

                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <button
                        type="button"
                        className="drift-reconcile-btn"
                        onClick={handleReconcile}
                        title="Reconcile workflow by running simulated hx generate"
                      >
                        ⚡ Reconcile Workflow (hx generate)
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleResetStale}
                        title="Reset to stale workflow baseline"
                      >
                        Reset to Stale
                      </button>
                    </div>
                  </div>

                  <CodeBlock
                    title="Terminal Simulation: hx check"
                    code={cliCheckOutput}
                    badge={driftFindings.length === 0 ? '✔ Exit Code 0 (Pass)' : `⚠ Exit Code 1 (${driftFindings.length} drift)`}
                  />

                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBlockStart: '-0.25rem' }}>
                    <button
                      type="button"
                      className="code-copy-btn"
                      onClick={() => setShowWorkflowYaml((prev) => !prev)}
                      aria-expanded={showWorkflowYaml}
                    >
                      {showWorkflowYaml ? 'Hide Active Workflow YAML' : 'Inspect Checked .github/workflows/ci.yml'}
                    </button>
                  </div>

                  {showWorkflowYaml && (
                    <CodeBlock
                      title="Active .github/workflows/ci.yml (Workflow Under Inspection)"
                      code={activeCheckedWorkflow}
                    />
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
