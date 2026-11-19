import { useRef, useState } from 'react';
import { HX_VERSION, INSTALL_METHODS } from '../data/siteData';
import { links } from '../lib/links';
import { CodeBlock } from './CodeBlock';
import { HeroGraph } from './HeroGraph';

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
      <HeroGraph />
      <div className="container hero-grid">
        <div className="hero-copy">
          <h1 id="main-content" tabIndex={-1}>
            CI config generated from what&rsquo;s actually in your repo.
          </h1>

          <p className="hero-lede">
            <code>hx</code> reads your lockfiles, version pins, Dockerfiles, compose services, and{' '}
            <code>.env.example</code>, then writes a GitHub Actions workflow, a Dependabot config, and Kubernetes
            manifests to match. It runs locally, makes no network calls, and gives the same output for the same repo
            every time.
          </p>

          <p className="hero-lede">
            Re-running it is safe. Changes are merged into your existing YAML, so comments, extra jobs, and anything
            marked <code># @heurix:preserve</code> stay where they are.
          </p>

          <div className="hero-actions">
            <a href={links.playground} className="btn btn-primary">
              Try it in the browser
            </a>
            <a href={links.docs('getting-started')} className="btn">
              Docs
            </a>
          </div>

          <p className="hero-release">
            v{HX_VERSION} adds CI path filters (<code>[ci].paths</code> and <code>[ci].paths_ignore</code>).{' '}
            <a href={links.docs('changelog')}>Changelog</a>
          </p>
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
            <span className="install-next-label">Then, from your repo root:</span>
            <CodeBlock title="First run" code={'hx generate --dry-run   # preview, writes nothing\nhx generate             # write + smart-merge\nhx check                # exit 1 on drift'} />
          </div>
        </aside>
      </div>
    </section>
  );
}
