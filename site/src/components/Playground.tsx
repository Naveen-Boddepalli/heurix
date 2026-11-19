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

const OUTPUT_TABS: { id: OutputTab; label: string; hint: string }[] = [
  { id: 'generate', label: 'hx generate', hint: 'YAML' },
  { id: 'scan', label: 'hx scan', hint: 'IR JSON' },
  { id: 'merge', label: 'hx diff', hint: 'Smart merge' },
  { id: 'drift', label: 'hx check', hint: 'Drift guard' },
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
  const [addFileError, setAddFileError] = useState<string | null>(null);

  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function selectPreset(id: string) {
    const next = PRESET_REPOS.find((p) => p.id === id) ?? PRESET_REPOS[0];
    setPresetId(next.id);
    setFiles(next.files.map((f) => ({ ...f })));
    setSelectedFilePath(next.files[0]?.path ?? '');
    setSelectedOutputFile('.github/workflows/ci.yml');
    setIsAddingFile(false);
    setAddFileError(null);
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
      setAddFileError(`"${cleanPath}" already exists. Pick another path or edit the existing file.`);
      return;
    }
    setAddFileError(null);

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
    : '# Turn on at least one language or deploy config file to generate YAML.';

  const activeFile = files.find((f) => f.path === selectedFilePath) ?? files[0];

  const existingCiSample =
    currentPreset.existingCiForMerge ??
    `name: CI\non:\n  push:\n    branches: [main]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      # @heurix:preserve\n      - name: Custom security & SBOM upload\n        run: ./scripts/upload-sbom.sh\n  slack_notify:\n    needs: test\n    if: failure()\n    runs-on: ubuntu-latest\n    steps:\n      - uses: slackapi/slack-github-action@v1`;

  const mergeResult = useMemo(
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
    return checkDrift(scanResult.context, activeCheckedWorkflow, scanResult.policy);
  }, [scanResult.context, scanResult.policy, activeCheckedWorkflow]);

  const policyStatus = scanResult.policy.error
    ? { tone: 'danger', label: 'Invalid .heurix.toml' }
    : scanResult.policy.source
      ? { tone: 'accent', label: '.heurix.toml applied' }
      : { tone: 'muted', label: 'No .heurix.toml' };

  const cliCheckOutput = useMemo(() => {
    if (driftFindings.length === 0) {
      return `$ hx check\nNo drift detected.\n\nexit code 0`;
    }
    const lines = [
      `$ hx check`,
      `Drift Detected (${driftFindings.length} issue(s)):`,
      '',
    ];
    for (const f of driftFindings) {
      lines.push(`[${f.severity}] ${f.file_path}: ${f.issue}`);
      lines.push(`  Recommendation: ${f.recommendation}`);
      lines.push('');
    }
    lines.push(`exit code 1`);
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
    setDriftNotice('Added a Redis dependency. The workflow has no redis service yet.');
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
    setDriftNotice('Bumped the runtime version. The workflow still pins the old one.');
  }

  function handleInjectUv() {
    setFiles((prev) => {
      if (prev.some((f) => f.path === 'uv.lock')) return prev;
      return [...prev, { path: 'uv.lock', enabled: true, content: '# uv lockfile v1\nversion = 1\n' }];
    });
    setDriftNotice('Added uv.lock. The workflow does not set up uv.');
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
    setDriftNotice('Added a Postgres service to docker-compose.yml. The workflow has no postgres service yet.');
  }

  function handleDuplicateService() {
    const base = scanResult.synthesized['.github/workflows/ci.yml'] ?? staleBaselineCi;
    const dupBlock = [
      '      db:',
      '        image: postgres:15',
      '        ports:',
      "          - '5432:5432'",
    ].join('\n');
    const withServices = /^    services:$/m.test(base)
      ? base.replace(/^    services:$/m, `    services:\n${dupBlock}`)
      : base.replace(/^(    runs-on: .*)$/m, `$1\n    services:\n      postgres:\n        image: postgres:16-alpine\n        ports:\n          - 5432:5432\n${dupBlock}`);
    setSimulatedCi(withServices);
    setDriftNotice(
      'Loaded a workflow like the ones older versions generated: "db" from compose and "postgres" from dependencies both use host port 5432.'
    );
  }

  function handleReconcile() {
    const currentGenerated = scanResult.synthesized['.github/workflows/ci.yml'];
    if (currentGenerated) {
      setSimulatedCi(currentGenerated);
      setDriftNotice('Replaced the workflow with the current hx generate output.');
    }
  }

  function handleResetStale() {
    setSimulatedCi(staleBaselineCi);
    setDriftNotice('Reset to the outdated workflow.');
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
          <h2>Playground</h2>
          <p>
            Pick a sample repo, or edit and toggle its files. The scan reruns in your browser on every change. It
            uses a TypeScript port of the detectors, so treat it as a preview of what the CLI will write.
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
              <span className={`status-chip is-${policyStatus.tone}`}>{policyStatus.label}</span>
              <span>
                {outputKeys.length} files, scanned in {scanResult.durationMs} ms
              </span>
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
                      onChange={(e) => {
                        setNewFilePath(e.target.value);
                        setAddFileError(null);
                      }}
                      placeholder="e.g. Dockerfile"
                      required
                    />
                    <button type="submit" className="btn btn-primary" style={{ minBlockSize: '2.25rem', paddingInline: '0.75rem', fontSize: '0.8125rem' }}>
                      Add
                    </button>
                  </div>
                  {addFileError && (
                    <p className="form-error" role="alert">
                      {addFileError}
                    </p>
                  )}
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
                    <code className="tab-cmd">{tab.label}</code>
                    <span className="tab-hint">{tab.hint}</span>
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
                  <details className="explain-box" open>
                    <summary className="explain-title">
                      <span>What it found</span>
                      <code>hx generate --explain</code>
                      <span className="explain-count">{scanResult.context.explain_log.length} steps</span>
                    </summary>
                    <ul className="explain-list">
                      {scanResult.context.explain_log.map((step, i) => {
                        const isWarn = step.startsWith('Warning:');
                        const isSkip = step.startsWith('Skipping');
                        return (
                          <li key={i} className={isWarn ? 'is-warn' : isSkip ? 'is-skip' : undefined}>
                            <span>{step}</span>
                          </li>
                        );
                      })}
                    </ul>
                  </details>

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
                          Download ZIP
                        </button>
                        <button
                          type="button"
                          className="export-btn"
                          onClick={handleDownloadScript}
                          title="Download bash setup script"
                        >
                          Setup script
                        </button>
                        <button
                          type="button"
                          className={`export-btn${copiedAll ? ' is-success' : ''}`}
                          onClick={handleCopyAll}
                          title="Copy all synthesized YAML configurations"
                        >
                          {copiedAll ? 'Copied' : 'Copy all'}
                        </button>
                      </div>
                    </div>
                  )}

                  <CodeBlock
                    title={activeOutputPath || 'No targets generated'}
                    code={activeOutputCode}
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
                    The detectors fill in this <code>ProjectContext</code> object, and the generators read only from
                    it.
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
                    <code># @heurix:preserve</code> survive regeneration intact while managed steps update. Put the
                    marker at the end of a <code>runs-on</code>, <code>services</code>, <code>needs</code>, or{' '}
                    <code>strategy</code> line to keep just that value.
                  </p>

                  <div className="merge-report" aria-label="Merge report">
                    <div className="merge-report-col">
                      <h3 className="merge-report-title is-warn">
                        Values that will be replaced <span className="count-pill">{mergeResult.replaced.length}</span>
                      </h3>
                      {mergeResult.replaced.length === 0 ? (
                        <p className="merge-report-empty">No hand-edited managed values are overwritten.</p>
                      ) : (
                        <ul>
                          {mergeResult.replaced.map((note) => (
                            <li key={note}>
                              <code>{note}</code>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div className="merge-report-col">
                      <h3 className="merge-report-title is-ok">
                        Kept by <code>@heurix:preserve</code>{' '}
                        <span className="count-pill">
                          {mergeResult.keptKeys.length + (existingCiSample.match(/^\s*# @heurix:preserve/gm)?.length ?? 0)}
                        </span>
                      </h3>
                      <ul>
                        {mergeResult.keptKeys.map((k) => (
                          <li key={k}>
                            <code>{k}</code> <span className="muted">(key-level)</span>
                          </li>
                        ))}
                        {(existingCiSample.match(/# @heurix:preserve\n\s*- name: (.+)/g) ?? []).map((m) => (
                          <li key={m}>
                            step <code>{m.split('- name: ')[1]}</code>
                          </li>
                        ))}
                        {mergeResult.keptKeys.length === 0 && !/^\s*# @heurix:preserve/m.test(existingCiSample) && (
                          <li className="muted">No preserve markers in this workflow.</li>
                        )}
                      </ul>
                    </div>
                  </div>

                  <div className="merge-compare">
                    <CodeBlock
                      title="Before: .github/workflows/ci.yml"
                      code={existingCiSample}
                      highlightDiff
                    />
                    <CodeBlock
                      title="After hx generate"
                      code={mergeResult.merged}
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
                      <span>{driftNotice}</span>
                    </div>
                  )}

                  <div className="drift-scenarios-bar">
                    <div className="drift-scenario-group" role="group" aria-label="Inject drift scenarios">
                      <span style={{ fontSize: '0.78125rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                        Change the repo:
                      </span>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleInjectRedis}
                        title="Add Redis dependency to codebase manifest"
                      >
                        + Redis dependency
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleBumpRuntime}
                        title="Bump runtime version in codebase"
                      >
                        Bump runtime
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleInjectUv}
                        title="Add uv.lock package manager file"
                      >
                        + uv.lock
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleInjectPostgres}
                        title="Add PostgreSQL container in compose"
                      >
                        + Postgres service
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleDuplicateService}
                        title="Load a workflow with two services on host port 5432"
                      >
                        Port collision
                      </button>
                    </div>

                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <button
                        type="button"
                        className="drift-reconcile-btn"
                        onClick={handleReconcile}
                        title="Reconcile workflow by running simulated hx generate"
                      >
                        Run hx generate
                      </button>
                      <button
                        type="button"
                        className="drift-scenario-btn"
                        onClick={handleResetStale}
                        title="Reset to stale workflow baseline"
                      >
                        Reset
                      </button>
                    </div>
                  </div>

                  <CodeBlock
                    title="hx check"
                    code={cliCheckOutput}
                    badge={driftFindings.length === 0 ? 'exit 0' : `exit 1`}
                  />

                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBlockStart: '-0.25rem' }}>
                    <button
                      type="button"
                      className="code-copy-btn"
                      onClick={() => setShowWorkflowYaml((prev) => !prev)}
                      aria-expanded={showWorkflowYaml}
                    >
                      {showWorkflowYaml ? 'Hide workflow' : 'Show the workflow being checked'}
                    </button>
                  </div>

                  {showWorkflowYaml && (
                    <CodeBlock
                      title=".github/workflows/ci.yml"
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
