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
    description: 'Tells Cursor to run hx instead of writing workflow YAML by hand.',
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
    description: 'Tells Claude Code which hx commands to run and when.',
    code: `# Build and CI/CD Instructions

## Heurix Deterministic Engine
This repository uses Heurix (hx) for CI/CD workflow generation and drift detection:
- hx scan - Inspect detected languages, runtimes, package managers, and backing services.
- hx generate - Synthesize schema-validated GitHub Actions, Dependabot, and Kubernetes YAML; smart-merges into existing files.
- hx diff - Preview the smart-merged result without writing; generate keeps '# @heurix:preserve' blocks.
- hx check - Verify zero drift between codebase manifest files and CI/CD workflows (exit code 0 = synchronized).`,
  },
  {
    id: 'agents',
    label: 'Agents (AGENTS.md)',
    filename: 'AGENTS.md',
    description: 'For agents that read AGENTS.md, such as Copilot, Windsurf, and Roo Code.',
    code: `# Autonomous Agent Conventions

## Configuration & Pipeline Rules
- Codebase manifests (pyproject.toml, package.json, Cargo.toml, go.mod, docker-compose.yml) are authoritative.
- Whenever a package or runtime version changes, run 'hx check'.
- If drift is detected, run 'hx generate' to reconcile workflows (it lists any hand-edited value it will replace).
- Custom steps in existing workflows marked with '# @heurix:preserve' must never be deleted or overwritten.`,
  },
  {
    id: 'prompt',
    label: 'System prompt',
    filename: 'system-prompt.txt',
    description: 'A system prompt you can paste into any chat assistant.',
    code: `You are an expert DevOps engineer assisting on this repository.
We use Heurix (hx CLI) to generate and maintain CI/CD pipelines and infrastructure configs deterministically.
Do NOT write GitHub Actions, Dependabot, or Kubernetes YAML from memory.
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
          <h2>Using hx with AI coding assistants</h2>
          <p>
            The site serves <code>llms.txt</code> and <code>llms-full.txt</code> so an assistant can read all of the
            docs in one request. Further down are rule files that tell an assistant to run <code>hx</code> rather
            than write workflow YAML from memory.
          </p>
        </div>

        <div className="visibility-grid">
          <div className="visibility-endpoints">
            <article className="endpoint-card">
              <div className="endpoint-path">/llms.txt</div>
              <p style={{ fontSize: '0.9375rem' }}>
                A short summary of what hx does, the main commands, and links to each doc.
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
                All {SITE_DOCS.docs.length} docs plus the design notes in one file ({SITE_DOCS.llmsFullLines} lines,{' '}
                {fullKb} KB), regenerated on every build.
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
              <div className="endpoint-path">Discovery tag</div>
              <p style={{ fontSize: '0.875rem' }}>
                <code>index.html</code> links to it so tools can find it:
              </p>
              <code>&lt;link rel=&quot;alternate&quot; type=&quot;text/plain&quot; title=&quot;llms.txt&quot; href=&quot;llms.txt&quot; /&gt;</code>
            </article>
          </div>

          <CodeBlock
            title="llms.txt (live preview)"
            code={SITE_DOCS.llmsTxt}
          />
        </div>

        {/* AI Assistant Rule Pack */}
        <div style={{ marginBlockStart: '2.5rem' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: '0.75rem', marginBlockEnd: '1rem' }}>
            <div>
              <h3 style={{ fontSize: '1.25rem', marginBlockEnd: '0.25rem' }}>
                Rule files for assistants
              </h3>
              <p style={{ fontSize: '0.9375rem', color: 'var(--text-secondary)' }}>
                Drop one into your repo so the assistant uses <code>hx</code> and leaves preserved steps alone.
              </p>
            </div>
            <button
              type="button"
              className={`btn${copiedRule ? ' btn-primary' : ''}`}
              onClick={copyCurrentRule}
              style={{ minBlockSize: '2.25rem' }}
            >
              {copiedRule ? `Copied ${activeRule.filename}` : `Copy ${activeRule.filename}`}
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
            />
          </div>
        </div>
      </div>
    </section>
  );
}
