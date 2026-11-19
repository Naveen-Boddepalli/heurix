import { CLI_COMMANDS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

export function CliExamples() {
  return (
    <section id="cli" className="section">
      <div className="container">
        <div className="section-header">
          <h2>Commands</h2>
          <p>
            Running <code>hx</code> on its own is the same as <code>hx generate</code>. It asks before changing an
            existing file; pass <code>--yes</code> to skip the prompts in CI.
          </p>
        </div>

        <div className="cli-grid">
          {CLI_COMMANDS.map((item) => (
            <article key={item.cmd} className="cli-card">
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
