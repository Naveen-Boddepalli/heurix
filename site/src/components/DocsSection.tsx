import { useState, type ReactNode } from 'react';
import { SITE_DOCS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

function renderInline(text: string): ReactNode[] {
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return tokens.map((tok, i) => {
    if (tok.startsWith('`') && tok.endsWith('`') && tok.length >= 2) {
      return <code key={i}>{tok.slice(1, -1)}</code>;
    }
    if (tok.startsWith('**') && tok.endsWith('**') && tok.length >= 4) {
      return <strong key={i}>{tok.slice(2, -2)}</strong>;
    }
    return tok;
  });
}

function MarkdownView({ markdown }: { markdown: string }) {
  const lines = markdown.split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Skip horizontal rules
    if (/^---+$/.test(line.trim())) {
      i += 1;
      continue;
    }

    // Fenced code block
    if (line.trim().startsWith('```')) {
      const lang = line.trim().slice(3).trim() || 'snippet';
      const codeLines: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i += 1;
      }
      i += 1; // skip closing fence
      blocks.push(<CodeBlock key={`code-${i}`} title={lang} code={codeLines.join('\n')} />);
      continue;
    }

    // Markdown table
    if (line.trim().startsWith('|') && i + 1 < lines.length && lines[i + 1].includes('---')) {
      const parseRow = (row: string) =>
        row
          .trim()
          .replace(/^\|/, '')
          .replace(/\|$/, '')
          .split('|')
          .map((c) => c.trim());

      const headers = parseRow(line);
      i += 2; // skip header + separator
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(parseRow(lines[i]));
        i += 1;
      }
      blocks.push(
        <div key={`tbl-${i}`} className="table-scroll">
          <table className="compare-table">
            <thead>
              <tr>
                {headers.map((h, hIdx) => (
                  <th key={hIdx} scope="col">
                    {renderInline(h)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, rIdx) => (
                <tr key={rIdx}>
                  {r.map((cell, cIdx) => (
                    <td key={cIdx}>{renderInline(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // Headings (mapped inside h2 section as h3/h4 to preserve hierarchy)
    if (line.startsWith('# ')) {
      blocks.push(<h3 key={`h-${i}`}>{renderInline(line.slice(2))}</h3>);
      i += 1;
      continue;
    }
    if (line.startsWith('## ')) {
      blocks.push(
        <h3 key={`h-${i}`} style={{ marginBlockStart: '0.5rem' }}>
          {renderInline(line.slice(3))}
        </h3>
      );
      i += 1;
      continue;
    }
    if (line.startsWith('### ')) {
      blocks.push(<h4 key={`h-${i}`}>{renderInline(line.slice(4))}</h4>);
      i += 1;
      continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      blocks.push(
        <p
          key={`bq-${i}`}
          style={{
            paddingInlineStart: '0.875rem',
            borderInlineStart: '3px solid var(--accent)',
            fontStyle: 'italic',
          }}
        >
          {renderInline(line.slice(2))}
        </p>
      );
      i += 1;
      continue;
    }

    // Unordered list
    if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
      const items: string[] = [];
      while (i < lines.length && (lines[i].trim().startsWith('- ') || lines[i].trim().startsWith('* '))) {
        items.push(lines[i].trim().slice(2));
        i += 1;
      }
      blocks.push(
        <ul key={`ul-${i}`}>
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ul>
      );
      continue;
    }

    // Empty line
    if (!line.trim()) {
      i += 1;
      continue;
    }

    // Paragraph
    const paraLines: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].startsWith('#') &&
      !lines[i].startsWith('```') &&
      !lines[i].startsWith('>') &&
      !lines[i].trim().startsWith('- ') &&
      !lines[i].trim().startsWith('* ') &&
      !lines[i].trim().startsWith('|')
    ) {
      paraLines.push(lines[i]);
      i += 1;
    }
    blocks.push(<p key={`p-${i}`}>{renderInline(paraLines.join(' '))}</p>);
  }

  return <div className="markdown-render">{blocks}</div>;
}

export function DocsSection() {
  const [selectedDocId, setSelectedDocId] = useState(SITE_DOCS.docs[1]?.id ?? SITE_DOCS.docs[0].id);
  const currentDoc = SITE_DOCS.docs.find((d) => d.id === selectedDocId) ?? SITE_DOCS.docs[0];

  return (
    <section id="docs" className="section">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">Documentation &amp; Guides</span>
          <h2>Reference synced directly from the repository</h2>
          <p>
            Every guide in <code>docs/</code> is built into this viewer and compiled automatically into{' '}
            <code>llms-full.txt</code> so human readers and AI assistants see the exact same specification.
          </p>
        </div>

        <div className="docs-layout">
          <nav className="docs-sidebar" aria-label="Documentation guides">
            <ul className="docs-nav-list">
              {SITE_DOCS.docs.map((doc) => (
                <li key={doc.id}>
                  <button
                    type="button"
                    className="docs-nav-btn"
                    aria-current={doc.id === currentDoc.id ? 'true' : undefined}
                    onClick={() => setSelectedDocId(doc.id)}
                  >
                    {doc.title}
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <article className="docs-article">
            <div className="docs-article-meta">
              <span>Source: {currentDoc.file}</span>
              <a
                href={`https://github.com/Naveen-Boddepalli/heurix/blob/main/${currentDoc.file}`}
                target="_blank"
                rel="noreferrer"
              >
                View on GitHub →
              </a>
            </div>
            <MarkdownView markdown={currentDoc.markdown} />
          </article>
        </div>
      </div>
    </section>
  );
}
