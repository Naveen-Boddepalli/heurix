import { useRef } from 'react';
import { CLI_COMMANDS } from '../data/siteData';
import { usePointerVars } from '../lib/usePointerVars';
import { links } from '../lib/links';
import { CodeBlock } from './CodeBlock';

export function CliExamples() {
  const gridRef = useRef<HTMLDivElement | null>(null);
  usePointerVars(gridRef, '.cli-card');

  return (
    <section id="cli" className="section">
      <div className="container">
        <div className="section-header reveal">
          <h2>Commands</h2>
          <p>
            Running <code>hx</code> on its own is the same as <code>hx generate</code>. It asks before changing an
            existing file; pass <code>--yes</code> to skip the prompts in CI. <code>hx scan</code> and{' '}
            <code>hx init</code> are covered in the <a href={links.docs('cli-reference')}>CLI reference</a>.
          </p>
        </div>

        <div className="cli-grid" ref={gridRef}>
          {CLI_COMMANDS.map((item, i) => (
            <article key={item.cmd} className="cli-card reveal" style={{ '--i': i % 2 } as React.CSSProperties}>
              <header style={{ display: 'grid', gap: '0.35rem' }}>
                <span className="card-tag">{item.cmd}</span>
                <h3>{item.title}</h3>
              </header>
              <p style={{ fontSize: '0.9375rem' }}>{item.desc}</p>
              <CodeBlock
                title={item.cmd}
                code={item.snippet}
                highlightDiff={item.cmd === 'hx diff'}
              />
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
