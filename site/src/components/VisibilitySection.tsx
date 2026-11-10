import { SITE_DOCS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

export function VisibilitySection() {
  const fullKb = (SITE_DOCS.llmsFullBytes / 1024).toFixed(1);

  return (
    <section id="visibility" className="section">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">AI &amp; Search Visibility</span>
          <h2>Machine-readable context via llms.txt</h2>
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
      </div>
    </section>
  );
}
