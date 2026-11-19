import { POLICY_EXAMPLE, POLICY_KEYS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

export function PolicySection() {
  return (
    <section id="config" className="section" aria-labelledby="config-title">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">Configuration</span>
          <h2 id="config-title">
            Zero-config by default. <code>.heurix.toml</code> when you need it.
          </h2>
          <p>
            Run <code>hx init</code> to create a commented policy. Every key is validated; an unparseable file makes{' '}
            <code>hx check</code> exit 1 with an &ldquo;Invalid Policy&rdquo; error instead of being silently
            ignored.
          </p>
        </div>

        <div className="policy-grid">
          <div className="policy-example">
            <CodeBlock title=".heurix.toml" code={POLICY_EXAMPLE} badge="hx init" />
            <div className="callout-stack">
              <div className="callout">
                <strong>Path filters (0.3.0).</strong> With only <code>paths_ignore</code>, CI gets a{' '}
                <code>paths-ignore:</code> block. With <code>paths</code> too, the ignores are appended to{' '}
                <code>paths</code> as <code>!pattern</code> entries, because GitHub rejects both keys on one event.
              </div>
              <div className="callout">
                <strong>Kubernetes is opt-in by shape.</strong> Manifests are generated for repos with a Dockerfile,
                or when <code>include_k8s = true</code>. A detected framework alone no longer produces a Deployment.
              </div>
              <div className="callout">
                <strong>Try it live.</strong> The FastAPI preset in the{' '}
                <a href="#playground">playground</a> ships a <code>.heurix.toml</code>; edit it and watch the
                trigger filters and runner change.
              </div>
            </div>
          </div>

          <div className="table-scroll">
            <table className="compare-table policy-table">
              <caption>Commonly used .heurix.toml keys</caption>
              <thead>
                <tr>
                  <th scope="col">Key</th>
                  <th scope="col">Example</th>
                  <th scope="col">What it does</th>
                </tr>
              </thead>
              <tbody>
                {POLICY_KEYS.map((row) => (
                  <tr key={`${row.section}.${row.key}`}>
                    <th scope="row">
                      <span className="policy-section-name">{row.section}</span>
                      <code>{row.key}</code>
                      {row.isNew && <span className="new-badge">New</span>}
                    </th>
                    <td>
                      <code className="policy-example-value">{row.example}</code>
                    </td>
                    <td>{row.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
