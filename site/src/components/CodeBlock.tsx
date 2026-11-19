import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';

interface CodeBlockProps {
  title: string;
  code: string;
  badge?: string;
  highlightDiff?: boolean;
  /** Briefly highlight lines that changed since the last render with the same title. */
  flashChanges?: boolean;
}

export function highlightYamlLine(line: string): ReactNode {
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

export function CodeBlock({ title, code, badge, highlightDiff = false, flashChanges = false }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const statusId = useId();
  const prevRef = useRef<{ title: string; code: string } | null>(null);
  const [changed, setChanged] = useState<{ lines: Set<number>; gen: number }>({ lines: new Set(), gen: 0 });

  // Compare against the previous output for the same file; lines that are new or edited get flashed
  useLayoutEffect(() => {
    if (!flashChanges) return;
    const prev = prevRef.current;
    prevRef.current = { title, code };
    if (!prev || prev.title !== title || prev.code === code) return;
    const before = new Map<string, number>();
    for (const l of prev.code.split('\n')) before.set(l, (before.get(l) ?? 0) + 1);
    const lines = new Set<number>();
    code.split('\n').forEach((l, i) => {
      const n = before.get(l) ?? 0;
      if (n > 0) before.set(l, n - 1);
      else if (l.trim()) lines.add(i);
    });
    if (lines.size) setChanged((c) => ({ lines, gen: c.gen + 1 }));
  }, [code, title, flashChanges]);

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
            className={`code-copy-btn${copied ? ' is-copied' : ''}`}
            onClick={handleCopy}
            aria-label={`Copy ${title}`}
          >
            <svg className="copy-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              {copied ? (
                <path d="M5 12.5l4.5 4.5L19 7.5" />
              ) : (
                <>
                  <rect x="9" y="9" width="11" height="11" rx="2" />
                  <path d="M5 15V6a2 2 0 0 1 2-2h9" />
                </>
              )}
            </svg>
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

            const flash = changed.lines.has(idx);
            if (flash) cls = cls ? `${cls} line-changed` : 'line-changed';
            return (
              <span
                key={flash ? `${idx}-${changed.gen}` : idx}
                className={cls || undefined}
                style={highlightDiff && cls ? ({ '--n': idx } as React.CSSProperties) : undefined}
              >
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
