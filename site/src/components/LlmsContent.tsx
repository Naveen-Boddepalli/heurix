import { SITE_DOCS } from '../data/docsData';
import { links } from '../lib/links';
import { CodeBlock } from './CodeBlock';

/** The llms.txt page of the docs. */
export function LlmsContent() {
  const fullKb = (SITE_DOCS.llmsFullBytes / 1024).toFixed(1);

  return (
    <div className="markdown-render">
      <h2 className="doc-title">llms.txt</h2>
      <p>
        The site serves two plain-text files so an AI assistant can read the docs in one request. For rule files
        that tell an assistant to run <code>hx</code> instead of writing workflow YAML itself, see{' '}
        <a href="#ai-integration">AI Assistant Integration</a>.
      </p>

      <div className="endpoint-list">
        <div className="endpoint-card">
          <a className="endpoint-path" href={links.asset('llms.txt')} target="_blank" rel="noreferrer">
            /llms.txt
          </a>
          <p>A short summary of what hx does, the main commands, and links to each doc.</p>
        </div>
        <div className="endpoint-card">
          <a className="endpoint-path" href={links.asset('llms-full.txt')} target="_blank" rel="noreferrer">
            /llms-full.txt
          </a>
          <p>
            All {SITE_DOCS.docs.length} docs plus the design notes in one file ({SITE_DOCS.llmsFullLines} lines,{' '}
            {fullKb} KB), regenerated on every build.
          </p>
        </div>
      </div>

      <p>
        Every page links to it from <code>&lt;head&gt;</code> so tools can find it:
      </p>
      <CodeBlock
        title="<head>"
        code={'<link rel="alternate" type="text/plain" title="llms.txt" href="llms.txt" />'}
      />

      <h3>Current llms.txt</h3>
      <CodeBlock title="llms.txt" code={SITE_DOCS.llmsTxt} />
    </div>
  );
}
