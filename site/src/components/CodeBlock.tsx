import { useId, useState, type ReactNode } from 'react';

interface CodeBlockProps {
  title: string;
  code: string;
  badge?: string;
  highlightDiff?: boolean;
}

function highlightYamlLine(line: string): ReactNode {
  // Whole-line preserve directive
  if (line.includes('@heurix:preserve') || line.includes('@autoyaml:preserve')) {
    return <span className="tok-preserve">{line}</span>;
  }

  // Full comment
  const trimmed = line.trimStart();
  if (trimmed.startsWith('#')) {
    return <span className="tok-comment">{line}</span>;
  }

  // Key-value pattern: e.g. "  runs-on: ubuntu-latest" or "  - name: Checkout"
  const kvMatch = line.match(/^(\s*(?:-\s+)?)([a-zA-Z0-9_-]+)(:)(.*)$/);
  if (kvMatch) {
    const [, indent, key, colon, rest] = kvMatch;

    // Check if rest has trailing comment
    let valuePart = rest;
    let commentPart = '';
    const hashIdx = rest.indexOf(' #');
    if (hashIdx !== -1) {
      valuePart = rest.slice(0, hashIdx);
      commentPart = rest.slice(hashIdx);
    }

    // Colorize value part
    let coloredVal: ReactNode = valuePart;
    const trimmedVal = valuePart.trim();

    if (trimmedVal.startsWith('${{') && trimmedVal.endsWith('}}')) {
      coloredVal = <span className="tok-secret">{valuePart}</span>;
    } else if (trimmedVal === 'true' || trimmedVal === 'false') {
      coloredVal = <span className="tok-bool">{valuePart}</span>;
    } else if (trimmedVal.includes('actions/') || trimmedVal.includes('astral-sh/') || trimmedVal.includes('Swatinem/')) {
      coloredVal = <span className="tok-action">{valuePart}</span>;
    } else if (/^['"].*['"]$/.test(trimmedVal)) {
      coloredVal = <span className="tok-str">{valuePart}</span>;
    } else if (/^\d+$/.test(trimmedVal)) {
      coloredVal = <span className="tok-num">{valuePart}</span>;
    }

    return (
      <>
        {indent}
        <span className="tok-key">{key}</span>
        <span className="tok-colon">{colon}</span>
        {coloredVal}
        {commentPart ? (
          commentPart.includes('@heurix:preserve') ? (
            <span className="tok-preserve">{commentPart}</span>
          ) : (
            <span className="tok-comment">{commentPart}</span>
          )
        ) : null}
      </>
    );
  }

  // Shell prompt line
  if (trimmed.startsWith('$ ')) {
    return (
      <>
        {line.slice(0, line.indexOf('$') + 1)}
        <span className="tok-cmd">{line.slice(line.indexOf('$') + 1)}</span>
      </>
    );
  }

  return line;
}

export function CodeBlock({ title, code, badge, highlightDiff = false }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const statusId = useId();

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  const lines = code.split('\n');

  return (
    <div className="code-box">
      <div className="code-box-header">
        <span className="code-box-title">{title}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {badge && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.75rem',
                color: 'var(--success)',
                fontWeight: 600,
              }}
            >
              {badge}
            </span>
          )}
          <button
            type="button"
            className="code-copy-btn"
            onClick={handleCopy}
            aria-label={`Copy ${title}`}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
          <span id={statusId} className="visually-hidden" aria-live="polite">
            {copied ? `${title} copied to clipboard` : ''}
          </span>
        </div>
      </div>
      <pre className="code-pre">
        <code>
          {lines.map((line, idx) => {
            let cls = '';
            if (highlightDiff) {
              if (line.includes('@heurix:preserve') || line.includes('@autoyaml:preserve')) {
                cls = 'diff-line-preserve';
              } else if (line.startsWith('+') && !line.startsWith('+++')) {
                cls = 'diff-line-add';
              } else if (line.startsWith('-') && !line.startsWith('---')) {
                cls = 'diff-line-del';
              }
            }

            return (
              <span key={idx} className={cls || undefined}>
                {highlightYamlLine(line)}
                {idx < lines.length - 1 ? '\n' : ''}
              </span>
            );
          })}
        </code>
      </pre>
    </div>
  );
}
