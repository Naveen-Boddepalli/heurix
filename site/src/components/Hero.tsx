import { useRef, useState } from 'react';
import { HERO_STATS, HX_VERSION, INSTALL_METHODS, RELEASES } from '../data/siteData';
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
          <a href="#changelog" className="release-banner">
            <span className="release-banner-tag">New in v{HX_VERSION}</span>
            <span>{RELEASES[0].headline}</span>
            <span aria-hidden="true">→</span>
          </a>

          <h1 id="main-content" tabIndex={-1}>
            Deterministic codebase scanner &amp; YAML synthesizer.
          </h1>

          <p className="hero-lede">
            Heurix (<code>hx</code>) reads your manifests, runtime pins, lockfiles, Dockerfiles, and env templates
            with pure-logic heuristics, then writes GitHub Actions CI, Dependabot, and Kubernetes YAML. No LLM, no
            network calls, and your hand edits survive every re-run.
          </p>

          <div className="hero-pills" aria-label="Key properties">
            <span className="pill">100% deterministic</span>
            <span className="pill">Offline</span>
            <span className="pill">AST smart merge</span>
            <span className="pill">Schema validated</span>
            <span className="pill">Drift guard</span>
          </div>

          <div className="hero-actions">
            <a href="#playground" className="btn btn-primary">
              Try interactive playground
            </a>
            <a href="#docs" className="btn">
              Read documentation
            </a>
          </div>

          <dl className="hero-stats">
            {HERO_STATS.map((s) => (
              <div key={s.label} className="hero-stat">
                <dt>{s.label}</dt>
                <dd>{s.value}</dd>
              </div>
            ))}
          </dl>
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

          <div className="install-next">
            <span className="install-next-label">Then, in your repo:</span>
            <CodeBlock title="First run" code={'hx generate --dry-run   # preview, writes nothing\nhx generate             # write + smart-merge\nhx check                # exit 1 on drift'} />
          </div>
        </aside>
      </div>
    </section>
  );
}
