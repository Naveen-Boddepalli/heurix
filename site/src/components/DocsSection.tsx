import { useMemo, useState, type ReactNode } from 'react';
import { SITE_DOCS } from '../data/siteData';
import { CodeBlock } from './CodeBlock';

function escapeRegExp(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function renderTextWithHighlight(raw: string, highlight?: string): ReactNode[] {
  if (!highlight || !highlight.trim()) return [raw];
  const q = highlight.trim();
  const parts = raw.split(new RegExp(`(${escapeRegExp(q)})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === q.toLowerCase() ? (
      <mark key={i} className="search-highlight">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

function renderInline(text: string, highlight?: string): ReactNode[] {
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return tokens.map((tok, i) => {
    if (tok.startsWith('`') && tok.endsWith('`') && tok.length >= 2) {
      return <code key={i}>{tok.slice(1, -1)}</code>;
    }
    if (tok.startsWith('**') && tok.endsWith('**') && tok.length >= 4) {
      return (
        <strong key={i}>
          {renderTextWithHighlight(tok.slice(2, -2), highlight)}
        </strong>
      );
    }
    return <span key={i}>{renderTextWithHighlight(tok, highlight)}</span>;
  });
}

function MarkdownView({ markdown, highlight }: { markdown: string; highlight?: string }) {
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
                    {renderInline(h, highlight)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, rIdx) => (
                <tr key={rIdx}>
                  {r.map((cell, cIdx) => (
                    <td key={cIdx}>{renderInline(cell, highlight)}</td>
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
      blocks.push(<h3 key={`h-${i}`}>{renderInline(line.slice(2), highlight)}</h3>);
      i += 1;
      continue;
    }
    if (line.startsWith('## ')) {
      blocks.push(
        <h3 key={`h-${i}`} style={{ marginBlockStart: '0.5rem' }}>
          {renderInline(line.slice(3), highlight)}
        </h3>
      );
      i += 1;
      continue;
    }
    if (line.startsWith('### ')) {
      blocks.push(<h4 key={`h-${i}`}>{renderInline(line.slice(4), highlight)}</h4>);
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
          {renderInline(line.slice(2), highlight)}
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
            <li key={idx}>{renderInline(it, highlight)}</li>
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
    blocks.push(<p key={`p-${i}`}>{renderInline(paraLines.join(' '), highlight)}</p>);
  }

  return <div className="markdown-render">{blocks}</div>;
}

export function DocsSection() {
  const [selectedDocId, setSelectedDocId] = useState(SITE_DOCS.docs[1]?.id ?? SITE_DOCS.docs[0].id);
  const [searchQuery, setSearchQuery] = useState('');

  const q = searchQuery.trim().toLowerCase();

  const docsWithMatches = useMemo(() => {
    return SITE_DOCS.docs.map((doc) => {
      if (!q) return { doc, matchCount: 0 };
      const titleMatches = (doc.title.toLowerCase().match(new RegExp(escapeRegExp(q), 'g')) || []).length;
      const contentMatches = (doc.markdown.toLowerCase().match(new RegExp(escapeRegExp(q), 'g')) || []).length;
      return {
        doc,
        matchCount: titleMatches * 3 + contentMatches,
      };
    });
  }, [q]);

  const visibleDocs = useMemo(() => {
    if (!q) return docsWithMatches;
    return docsWithMatches.filter((item) => item.matchCount > 0);
  }, [docsWithMatches, q]);

  // If search query is active and currentDoc is not among visibleDocs, fall back to first visible doc
  const effectiveDocId = useMemo(() => {
    if (!q || visibleDocs.length === 0) return selectedDocId;
    if (visibleDocs.some((item) => item.doc.id === selectedDocId)) {
      return selectedDocId;
    }
    return visibleDocs[0]?.doc.id ?? selectedDocId;
  }, [q, selectedDocId, visibleDocs]);

  const currentDocItem =
    docsWithMatches.find((item) => item.doc.id === effectiveDocId) ?? docsWithMatches[0];
  const currentDoc = currentDocItem.doc;

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
            <div className="docs-search-box">
              <input
                type="search"
                className="docs-search-input"
                placeholder="Search guides & heuristics..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                aria-label="Search documentation"
              />
              {searchQuery && (
                <button
                  type="button"
                  className="docs-search-clear"
                  onClick={() => setSearchQuery('')}
                  aria-label="Clear search"
                >
                  ×
                </button>
              )}
            </div>

            {visibleDocs.length === 0 ? (
              <div className="docs-empty-search">
                <span aria-hidden="true">🔎</span>
                <span>No guides matching &ldquo;{searchQuery}&rdquo;.</span>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setSearchQuery('')}
                  style={{ minBlockSize: '1.75rem', fontSize: '0.75rem' }}
                >
                  Clear search
                </button>
              </div>
            ) : (
              <ul className="docs-nav-list">
                {visibleDocs.map(({ doc, matchCount }) => (
                  <li key={doc.id}>
                    <button
                      type="button"
                      className="docs-nav-btn"
                      aria-current={doc.id === currentDoc.id ? 'true' : undefined}
                      onClick={() => setSelectedDocId(doc.id)}
                    >
                      <span>{doc.title}</span>
                      {q && matchCount > 0 && (
                        <span className="docs-match-badge" title={`${matchCount} match(es)`}>
                          {matchCount}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
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

            {q && currentDocItem.matchCount > 0 && (
              <div className="drift-notice">
                <span aria-hidden="true">🔍</span>
                <span>
                  Found <strong>{currentDocItem.matchCount}</strong> match(es) for &ldquo;{searchQuery}&rdquo; in this guide.
                </span>
              </div>
            )}

            <MarkdownView markdown={currentDoc.markdown} highlight={q} />
          </article>
        </div>
      </div>
    </section>
  );
}
