import { POLICY_EXAMPLE, POLICY_KEYS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

export function PolicySection() {
  return (
    <section id="config" className="section" aria-labelledby="config-title">
      <div className="container">
        <div className="section-header">
          <h2 id="config-title">Configuration</h2>
          <p>
            No config file is needed. To change the defaults, run <code>hx init</code> to create a commented{' '}
            <code>.heurix.toml</code>. If the file can&rsquo;t be parsed, <code>hx check</code> fails with an
            &ldquo;Invalid Policy&rdquo; error instead of quietly ignoring it.
          </p>
        </div>

        <div className="policy-grid">
          <div className="policy-example">
            <CodeBlock title=".heurix.toml" code={POLICY_EXAMPLE} />
            <div className="policy-notes">
              <h3>Path filters</h3>
              <p>
                With only <code>paths_ignore</code>, the workflow gets a <code>paths-ignore:</code> block. If you set{' '}
                <code>paths</code> as well, the ignores are added to <code>paths</code> as <code>!pattern</code>{' '}
                entries, because GitHub doesn&rsquo;t allow both keys on the same event.
              </p>
              <h3>Kubernetes</h3>
              <p>
                Manifests are only generated when the repo has a Dockerfile, or when you set{' '}
                <code>include_k8s = true</code>.
              </p>
              <p>
                The FastAPI sample in the <a href="#playground">playground</a> includes a <code>.heurix.toml</code>{' '}
                you can edit.
              </p>
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
                      {row.isNew && <span className="new-badge">since 0.3.0</span>}
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
