import { useRef, useState } from 'react';
import { INSTALL_METHODS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

export function Hero() {
  const [selectedId, setSelectedId] = useState(INSTALL_METHODS[0].id);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex = -1;
    if (e.key === 'ArrowRight') nextIndex = (index + 1) % INSTALL_METHODS.length;
    else if (e.key === 'ArrowLeft') nextIndex = (index - 1 + INSTALL_METHODS.length) % INSTALL_METHODS.length;
    else if (e.key === 'Home') nextIndex = 0;
    else if (e.key === 'End') nextIndex = INSTALL_METHODS.length - 1;

    if (nextIndex !== -1) {
      e.preventDefault();
      setSelectedId(INSTALL_METHODS[nextIndex].id);
      tabRefs.current[nextIndex]?.focus();
    }
  }

  return (
    <section id="top" className="hero">
      <div className="container hero-grid">
        <div className="hero-copy">
          <div className="hero-pills">
            <span className="pill">100% Deterministic</span>
            <span className="pill">Offline-Capable (&lt;50ms)</span>
            <span className="pill">AST Smart Merge</span>
            <span className="pill">Schema Validated</span>
          </div>

          <h1 id="main-content" tabIndex={-1}>
            Deterministic codebase scanner &amp; YAML synthesizer.
          </h1>

          <p style={{ fontSize: '1.125rem' }}>
            Heurix (<code>hx</code>) inspects repository manifests, runtime pins, lockfiles, Dockerfiles, and
            environment templates using pure-logic heuristics—then synthesizes production-ready GitHub Actions CI/CD,
            Dependabot, and Kubernetes YAML without LLM hallucinations or overwriting custom edits.
          </p>

          <div className="hero-actions">
            <a href="#playground" className="btn btn-primary">
              Try interactive playground
            </a>
            <a href="#docs" className="btn">
              Read documentation
            </a>
            <a href="llms.txt" className="btn">
              View llms.txt
            </a>
          </div>
        </div>

        <aside className="install-card" aria-label="Install Heurix">
          <div role="tablist" aria-label="Installation methods" className="tablist">
            {INSTALL_METHODS.map((method, idx) => (
              <button
                key={method.id}
                ref={(el) => {
                  tabRefs.current[idx] = el;
                }}
                type="button"
                role="tab"
                id={`install-tab-${method.id}`}
                aria-selected={selectedId === method.id}
                tabIndex={selectedId === method.id ? 0 : -1}
                className="tab-btn"
                onClick={() => setSelectedId(method.id)}
                onKeyDown={(e) => handleKeyDown(e, idx)}
              >
                {method.label}
              </button>
            ))}
          </div>

          {INSTALL_METHODS.map((method) => {
            const isSelected = selectedId === method.id;
            return (
              <div
                key={method.id}
                role="tabpanel"
                aria-labelledby={`install-tab-${method.id}`}
                hidden={!isSelected}
                tabIndex={isSelected ? 0 : undefined}
              >
                <div className="tabpanel-body" style={{ display: 'grid', gap: '0.75rem' }}>
                  <CodeBlock title={`Install via ${method.label}`} code={method.command} />
                  <p style={{ fontSize: '0.875rem' }}>{method.note}</p>
                </div>
              </div>
            );
          })}
        </aside>
      </div>
    </section>
  );
}
