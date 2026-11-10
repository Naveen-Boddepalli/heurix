import { CLI_COMMANDS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

export function CliExamples() {
  return (
    <section id="cli" className="section">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">CLI Workflows &amp; Examples</span>
          <h2>Transparent commands built for developer trust</h2>
          <p>
            Every command explains what it detected and previews diffs before touching disk. Run{' '}
            <code>hx</code> interactively locally or pass <code>--yes</code> in headless automation.
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
