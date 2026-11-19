import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { SITE_DOCS } from '../data/docsData';
import { CodeBlock } from './CodeBlock';
import { LlmsContent } from './LlmsContent';
import { PolicyContent } from './PolicyContent';

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

    // Headings: the page has a hidden h1, so a doc's # title becomes h2
    if (line.startsWith('# ')) {
      blocks.push(
        <h2 key={`h-${i}`} className="doc-title">
          {renderInline(line.slice(2), highlight)}
        </h2>
      );
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

    // Ordered list
    if (/^\s*\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s/.test(lines[i])) {
        let item = lines[i].trim().replace(/^\d+\.\s+/, '');
        i += 1;
        // Indented continuation lines belong to the same item
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*(\d+\.|-|\*)\s/.test(lines[i])) {
          item += ` ${lines[i].trim()}`;
          i += 1;
        }
        items.push(item);
      }
      blocks.push(
        <ol key={`ol-${i}`}>
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it, highlight)}</li>
          ))}
        </ol>
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
      !/^\s*\d+\.\s/.test(lines[i]) &&
      !lines[i].trim().startsWith('|')
    ) {
      paraLines.push(lines[i]);
      i += 1;
    }
    blocks.push(<p key={`p-${i}`}>{renderInline(paraLines.join(' '), highlight)}</p>);
  }

  return <div className="markdown-render">{blocks}</div>;
}

interface DocView {
  id: string;
  title: string;
  group: string;
  /** Repo file the page comes from, for the "View on GitHub" link. */
  file: string | null;
  /** Text used for search matching. */
  searchText: string;
  render: (highlight: string) => ReactNode;
}

const CUSTOM_PAGES: Record<string, { after: string; view: DocView }> = {
  configuration: {
    after: 'cli-reference',
    view: {
      id: 'configuration',
      title: 'Configuration',
      group: 'Reference',
      file: null,
      searchText:
        '.heurix.toml configuration policy hx init runner paths paths_ignore include_k8s include_dependabot action_shas secrets deploy kubernetes image_tag overrides',
      render: () => <PolicyContent />,
    },
  },
  'llms-txt': {
    after: 'changelog',
    view: {
      id: 'llms-txt',
      title: 'llms.txt',
      group: 'Project',
      file: 'llms.txt',
      searchText: `llms.txt llms-full.txt ${SITE_DOCS.llmsTxt}`,
      render: () => <LlmsContent />,
    },
  },
};

function buildDocViews(): DocView[] {
  const views: DocView[] = [];
  for (const doc of SITE_DOCS.docs) {
    views.push({
      id: doc.id,
      title: doc.title,
      group: doc.group,
      file: doc.file,
      searchText: doc.markdown,
      render: (highlight) => <MarkdownView markdown={doc.markdown} highlight={highlight} />,
    });
    for (const custom of Object.values(CUSTOM_PAGES)) {
      if (custom.after === doc.id) views.push(custom.view);
    }
  }
  return views;
}

const DOC_VIEWS = buildDocViews();
const DEFAULT_DOC = 'getting-started';

function docIdFromHash(): string {
  const id = decodeURIComponent(window.location.hash.slice(1));
  return DOC_VIEWS.some((d) => d.id === id) ? id : DEFAULT_DOC;
}

function countMatches(haystack: string, q: string): number {
  return (haystack.toLowerCase().match(new RegExp(escapeRegExp(q), 'g')) || []).length;
}

export function DocsSection() {
  const [selectedDocId, setSelectedDocId] = useState(docIdFromHash);
  const [searchQuery, setSearchQuery] = useState('');
  const articleRef = useRef<HTMLElement | null>(null);

  const q = searchQuery.trim().toLowerCase();

  // Keep the selected doc in sync with the URL hash (links, back/forward buttons).
  useEffect(() => {
    const onHash = () => setSelectedDocId(docIdFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const docsWithMatches = useMemo(
    () =>
      DOC_VIEWS.map((doc) => ({
        doc,
        matchCount: q ? countMatches(doc.title, q) * 3 + countMatches(doc.searchText, q) : 0,
      })),
    [q]
  );

  const visibleDocs = useMemo(
    () => (q ? docsWithMatches.filter((item) => item.matchCount > 0) : docsWithMatches),
    [docsWithMatches, q]
  );

  const groupedDocs = useMemo(() => {
    const groups = new Map<string, typeof visibleDocs>();
    for (const item of visibleDocs) {
      const list = groups.get(item.doc.group) ?? [];
      list.push(item);
      groups.set(item.doc.group, list);
    }
    return [...groups.entries()];
  }, [visibleDocs]);

  const currentIndex = Math.max(
    0,
    DOC_VIEWS.findIndex((d) => d.id === selectedDocId)
  );
  const currentDoc = DOC_VIEWS[currentIndex];
  const currentMatches = docsWithMatches[currentIndex]?.matchCount ?? 0;
  const prevDoc = DOC_VIEWS[currentIndex - 1];
  const nextDoc = DOC_VIEWS[currentIndex + 1];

  useEffect(() => {
    document.title = `${currentDoc.title} · Heurix docs`;
  }, [currentDoc.title]);

  function openDoc(id: string) {
    if (id !== selectedDocId) {
      window.location.hash = id;
    }
    setSelectedDocId(id);
    const top = (articleRef.current?.getBoundingClientRect().top ?? 0) + window.scrollY - 80;
    if (window.scrollY > top) window.scrollTo({ top, behavior: 'instant' as ScrollBehavior });
  }

  return (
    <section id="docs" className="page-section">
      <h1 className="visually-hidden">Heurix documentation</h1>
      <div className="container container-wide">
        <div className="docs-layout">
          <nav className="docs-sidebar" aria-label="Documentation">
            <div className="docs-search-box">
              <input
                type="search"
                className="docs-search-input"
                placeholder="Search the docs"
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

            <label className="docs-mobile-picker">
              <span className="visually-hidden">Choose a page</span>
              <select className="form-select" value={currentDoc.id} onChange={(e) => openDoc(e.target.value)}>
                {groupedDocs.map(([group, items]) => (
                  <optgroup key={group} label={group}>
                    {items.map(({ doc, matchCount }) => (
                      <option key={doc.id} value={doc.id}>
                        {doc.title}
                        {q && matchCount > 0 ? ` (${matchCount})` : ''}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>

            {visibleDocs.length === 0 ? (
              <div className="docs-empty-search">
                <span>No pages match &ldquo;{searchQuery}&rdquo;.</span>
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
              <div className="docs-nav-groups">
                {groupedDocs.map(([group, items]) => (
                  <div key={group} className="docs-nav-group">
                    <h2 className="docs-nav-group-title">{group}</h2>
                    <ul className="docs-nav-list">
                      {items.map(({ doc, matchCount }) => (
                        <li key={doc.id}>
                          <a
                            href={`#${doc.id}`}
                            className="docs-nav-btn"
                            aria-current={doc.id === currentDoc.id ? 'page' : undefined}
                            onClick={(e) => {
                              e.preventDefault();
                              openDoc(doc.id);
                            }}
                          >
                            <span>{doc.title}</span>
                            {q && matchCount > 0 && (
                              <span className="docs-match-badge" title={`${matchCount} match(es)`}>
                                {matchCount}
                              </span>
                            )}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </nav>

          <article id="main-content" tabIndex={-1} className="docs-article" ref={articleRef}>
            {currentDoc.file && (
              <div className="docs-article-meta">
                <span>{currentDoc.file}</span>
                <a
                  href={`https://github.com/Naveen-Boddepalli/heurix/blob/main/${currentDoc.file}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  View on GitHub
                </a>
              </div>
            )}

            {q && currentMatches > 0 && (
              <div className="drift-notice">
                <span>
                  {currentMatches} match{currentMatches === 1 ? '' : 'es'} for &ldquo;{searchQuery}&rdquo; on this
                  page.
                </span>
              </div>
            )}

            {currentDoc.render(q)}

            <nav className="docs-pager" aria-label="Previous and next page">
              {prevDoc ? (
                <a
                  href={`#${prevDoc.id}`}
                  className="docs-pager-link"
                  onClick={(e) => {
                    e.preventDefault();
                    openDoc(prevDoc.id);
                  }}
                >
                  <span className="docs-pager-label">Previous</span>
                  <span>{prevDoc.title}</span>
                </a>
              ) : (
                <span />
              )}
              {nextDoc && (
                <a
                  href={`#${nextDoc.id}`}
                  className="docs-pager-link is-next"
                  onClick={(e) => {
                    e.preventDefault();
                    openDoc(nextDoc.id);
                  }}
                >
                  <span className="docs-pager-label">Next</span>
                  <span>{nextDoc.title}</span>
                </a>
              )}
            </nav>
          </article>
        </div>
      </div>
    </section>
  );
}
