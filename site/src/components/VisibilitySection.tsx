import { useState, useRef } from 'react';
import { SITE_DOCS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

interface AssistantRule {
  id: string;
  label: string;
  filename: string;
  description: string;
  code: string;
}

const AI_RULES: AssistantRule[] = [
  {
    id: 'cursor',
    label: 'Cursor (.cursorrules)',
    filename: '.cursorrules',
    description: 'Directs Cursor to run hx CLI commands rather than handwriting YAML from LLM memory.',
    code: `# CI/CD & DevOps Automation Rules
- NEVER handwrite or manually modify .github/workflows/*.yml or Kubernetes YAML from scratch.
- Always use 'hx' (Heurix CLI) to analyze codebase and generate pipeline files:
  - Run 'hx generate' to synthesize or update GitHub Actions workflows.
  - Run 'hx check' to verify that existing workflows match current dependencies and runtimes.
- When adding custom steps to workflows (e.g. Slack notifications, deployment webhooks), preserve them with '# @heurix:preserve'.`,
  },
  {
    id: 'claude',
    label: 'Claude Code (CLAUDE.md)',
    filename: 'CLAUDE.md',
    description: 'Instructions for Claude Code CLI to run hx scan, hx generate, and hx check.',
    code: `# Build and CI/CD Instructions

## Heurix Deterministic Engine
This repository uses Heurix (hx) for CI/CD workflow generation and drift detection:
- hx scan - Inspect detected languages, runtimes, package managers, and backing services.
- hx generate - Synthesize schema-validated GitHub Actions workflows and Dockerfiles.
- hx generate --update - Reconcile existing workflows while preserving '# @heurix:preserve' blocks.
- hx check - Verify zero drift between codebase manifest files and CI/CD workflows (exit code 0 = synchronized).`,
  },
  {
    id: 'agents',
    label: 'Agents (AGENTS.md)',
    filename: 'AGENTS.md',
    description: 'Conventions for Antigravity, Roo Code, Windsurf, and Copilot autonomous agents.',
    code: `# Autonomous Agent Conventions

## Configuration & Pipeline Rules
- Codebase manifests (pyproject.toml, package.json, Cargo.toml, go.mod, docker-compose.yml) are authoritative.
- Whenever a package or runtime version changes, run 'hx check'.
- If drift is detected, run 'hx generate --update' to reconcile workflows automatically.
- Custom steps in existing workflows marked with '# @heurix:preserve' must never be deleted or overwritten.`,
  },
  {
    id: 'prompt',
    label: 'One-Shot Prompt',
    filename: 'system-prompt.txt',
    description: 'Drop-in system prompt for any AI chat or custom coding assistant.',
    code: `You are an expert DevOps engineer assisting on this repository.
We use Heurix (hx CLI) to generate and maintain CI/CD pipelines and infrastructure configs deterministically.
Do NOT write GitHub Actions YAML or Dockerfiles from memory.
Instead:
1. Recommend running 'hx scan' to inspect detected frameworks and services.
2. Recommend running 'hx generate' to synthesize verified YAML configs.
3. Recommend running 'hx check' in pre-commit and CI to catch configuration drift before merge.`,
  },
];

export function VisibilitySection() {
  const fullKb = (SITE_DOCS.llmsFullBytes / 1024).toFixed(1);
  const [activeRuleId, setActiveRuleId] = useState(AI_RULES[0].id);
  const [copiedRule, setCopiedRule] = useState(false);
  const ruleTabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const activeRule = AI_RULES.find((r) => r.id === activeRuleId) ?? AI_RULES[0];

  function copyCurrentRule() {
    navigator.clipboard.writeText(activeRule.code).then(() => {
      setCopiedRule(true);
      setTimeout(() => setCopiedRule(false), 2000);
    });
  }

  function handleRuleKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = -1;
    if (e.key === 'ArrowRight') next = (index + 1) % AI_RULES.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + AI_RULES.length) % AI_RULES.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = AI_RULES.length - 1;

    if (next !== -1) {
      e.preventDefault();
      setActiveRuleId(AI_RULES[next].id);
      ruleTabRefs.current[next]?.focus();
    }
  }

  return (
    <section id="visibility" className="section">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">AI &amp; Search Visibility</span>
          <h2>Machine-readable context via llms.txt &amp; AI Integration Pack</h2>
          <p>
            Heurix publishes structured Markdown endpoints following the <code>llmstxt.org</code> standard and
            exposes <code>&lt;link rel=&quot;alternate&quot; type=&quot;text/plain&quot;&gt;</code> metadata so
            coding assistants, search agents, and CLI tools can ingest the complete specification in one request.
          </p>
        </div>

        <div className="visibility-grid">
          <div className="visibility-endpoints">
            <article className="endpoint-card">
              <div className="endpoint-path">/llms.txt</div>
              <p style={{ fontSize: '0.9375rem' }}>
                Concise architectural summary, differentiators, minimal CLI examples, and curated documentation
                links indexed for LLM context windows.
              </p>
              <div className="hero-actions">
                <a href="llms.txt" className="btn btn-primary" target="_blank" rel="noreferrer">
                  Open /llms.txt
                </a>
              </div>
            </article>

            <article className="endpoint-card">
              <div className="endpoint-path">/llms-full.txt</div>
              <p style={{ fontSize: '0.9375rem' }}>
                All {SITE_DOCS.docs.length} repository guides and the master architecture plan concatenated at build
                time ({SITE_DOCS.llmsFullLines} lines, {fullKb} KB) so it can never drift from source docs.
              </p>
              <div className="hero-actions">
                <a href="llms-full.txt" className="btn" target="_blank" rel="noreferrer">
                  Open /llms-full.txt
                </a>
                <a href="robots.txt" className="btn" target="_blank" rel="noreferrer">
                  robots.txt
                </a>
              </div>
            </article>

            <article className="endpoint-card">
              <div className="endpoint-path">Head Discovery Tag</div>
              <p style={{ fontSize: '0.875rem' }}>
                Embedded directly in <code>index.html</code> for automatic agent discovery:
              </p>
              <code>&lt;link rel=&quot;alternate&quot; type=&quot;text/plain&quot; title=&quot;llms.txt&quot; href=&quot;llms.txt&quot; /&gt;</code>
            </article>
          </div>

          <CodeBlock
            title="llms.txt (live preview)"
            code={SITE_DOCS.llmsTxt}
            badge="llmstxt.org spec"
          />
        </div>

        {/* AI Assistant Rule Pack */}
        <div style={{ marginBlockStart: '2.5rem' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: '0.75rem', marginBlockEnd: '1rem' }}>
            <div>
              <h3 style={{ fontSize: '1.25rem', marginBlockEnd: '0.25rem' }}>
                🤖 AI Coding Assistant Integration Pack
              </h3>
              <p style={{ fontSize: '0.9375rem', color: 'var(--text-secondary)' }}>
                Keep your AI assistants from hallucinating outdated actions or breaking custom steps.
              </p>
            </div>
            <button
              type="button"
              className={`btn${copiedRule ? ' btn-primary' : ''}`}
              onClick={copyCurrentRule}
              style={{ minBlockSize: '2.25rem' }}
            >
              <span aria-hidden="true">{copiedRule ? '✔' : '📋'}</span>
              {copiedRule ? `Copied ${activeRule.filename}!` : `Copy ${activeRule.filename}`}
            </button>
          </div>

          <div role="tablist" aria-label="AI coding assistant rule files" className="tablist" style={{ marginBlockEnd: '1rem' }}>
            {AI_RULES.map((rule, idx) => (
              <button
                key={rule.id}
                ref={(el) => {
                  ruleTabRefs.current[idx] = el;
                }}
                type="button"
                role="tab"
                id={`ai-rule-tab-${rule.id}`}
                aria-selected={activeRuleId === rule.id}
                tabIndex={activeRuleId === rule.id ? 0 : -1}
                className="tab-btn"
                onClick={() => setActiveRuleId(rule.id)}
                onKeyDown={(e) => handleRuleKeyDown(e, idx)}
              >
                {rule.label}
              </button>
            ))}
          </div>

          <div
            role="tabpanel"
            aria-labelledby={`ai-rule-tab-${activeRule.id}`}
            tabIndex={0}
          >
            <p style={{ fontSize: '0.875rem', marginBlockEnd: '0.75rem', color: 'var(--text-secondary)' }}>
              {activeRule.description}
            </p>
            <CodeBlock
              title={activeRule.filename}
              code={activeRule.code}
              badge="Deterministic rule"
            />
          </div>
        </div>
      </div>
    </section>
  );
}
