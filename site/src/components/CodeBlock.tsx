import { useId, useState } from 'react';

interface CodeBlockProps {
  title: string;
  code: string;
  badge?: string;
  highlightDiff?: boolean;
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
          {highlightDiff
            ? lines.map((line, idx) => {
                let cls = '';
                if (line.includes('@heurix:preserve') || line.includes('@autoyaml:preserve')) {
                  cls = 'diff-line-preserve';
                } else if (line.startsWith('+') && !line.startsWith('+++')) {
                  cls = 'diff-line-add';
                } else if (line.startsWith('-') && !line.startsWith('---')) {
                  cls = 'diff-line-del';
                }
                return (
                  <span key={idx} className={cls || undefined}>
                    {line}
                    {idx < lines.length - 1 ? '\n' : ''}
                  </span>
                );
              })
            : code}
        </code>
      </pre>
    </div>
  );
}
