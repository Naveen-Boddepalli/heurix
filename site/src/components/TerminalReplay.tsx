import { useEffect, useRef, useState } from 'react';
import { prefersReducedMotion } from '../lib/useReducedMotion';
import { highlightYamlLine } from './CodeBlock';

type LineKind = 'log' | 'hit' | 'warn' | 'gap' | 'write' | 'yaml' | 'done';
interface ReplayLine {
  kind: LineKind;
  text: string;
}

const COMMAND = 'hx generate --dry-run';
const FIRST_RUN = 'hx generate --dry-run   # preview, writes nothing\nhx generate             # write + smart-merge\nhx check                # exit 1 on drift';
const YAML_PREVIEW_LINES = 14;
const DELAY: Record<LineKind, number> = { log: 260, hit: 220, warn: 260, gap: 320, write: 200, yaml: 55, done: 400 };

/**
 * Builds the transcript by running the same TypeScript port of the detectors the playground
 * uses, on the first sample repo. Loaded lazily so the home page bundle stays small.
 */
async function buildTranscript(): Promise<{ repo: string; lines: ReplayLine[] }> {
  const [{ runHeurixScan }, { PRESET_REPOS }] = await Promise.all([
    import('../engine/heuristics'),
    import('../engine/presets'),
  ]);
  const preset = PRESET_REPOS[0];
  const result = runHeurixScan(preset.repoName, preset.files);
  const lines: ReplayLine[] = [];

  for (const entry of result.context.explain_log.slice(0, 10)) {
    const kind: LineKind = /^warning/i.test(entry) ? 'warn' : /^(Detected|Inferred|Loaded)/.test(entry) ? 'hit' : 'log';
    lines.push({ kind, text: entry });
  }
  lines.push({ kind: 'gap', text: '' });
  for (const [path, body] of Object.entries(result.synthesized)) {
    lines.push({ kind: 'write', text: `would write ${path}  (${body.split('\n').length} lines)` });
  }
  lines.push({ kind: 'gap', text: '' });
  const ci = result.synthesized['.github/workflows/ci.yml'] ?? '';
  const yaml = ci.split('\n');
  lines.push({ kind: 'log', text: '--- .github/workflows/ci.yml' });
  for (const l of yaml.slice(0, YAML_PREVIEW_LINES)) lines.push({ kind: 'yaml', text: l });
  if (yaml.length > YAML_PREVIEW_LINES) lines.push({ kind: 'log', text: `# ... ${yaml.length - YAML_PREVIEW_LINES} more lines` });
  lines.push({ kind: 'done', text: `Dry run finished in ${result.durationMs} ms. Nothing written.` });
  lines.push({ kind: 'gap', text: '' });
  lines.push({ kind: 'log', text: '# next: hx generate   (write + smart-merge)' });
  lines.push({ kind: 'log', text: '#       hx check      (exit 1 on drift)' });
  return { repo: preset.repoName, lines };
}

export function TerminalReplay({ active = true }: { active?: boolean }) {
  const [transcript, setTranscript] = useState<{ repo: string; lines: ReplayLine[] } | null>(null);
  const [typed, setTyped] = useState(0);
  const [shown, setShown] = useState(0);
  const [inView, setInView] = useState(false);
  const [run, setRun] = useState(0);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const screenRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (!active || transcript) return;
    let cancelled = false;
    buildTranscript().then((t) => {
      if (!cancelled) setTranscript(t);
    });
    return () => {
      cancelled = true;
    };
  }, [active, transcript]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { threshold: 0.3 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // Reduced motion: jump straight to the finished transcript
  useEffect(() => {
    if (transcript && prefersReducedMotion()) {
      setTyped(COMMAND.length);
      setShown(transcript.lines.length);
    }
  }, [transcript, run]);

  // Playback: type the command, then stream lines. Pauses while off screen or on another tab.
  useEffect(() => {
    if (!transcript || !active || !inView) return;
    let id: number | undefined;
    if (typed < COMMAND.length) {
      id = window.setTimeout(() => setTyped((n) => n + 1), typed === 0 ? 500 : 38 + Math.random() * 40);
    } else if (shown < transcript.lines.length) {
      const next = transcript.lines[shown];
      id = window.setTimeout(() => setShown((n) => n + 1), shown === 0 ? 380 : DELAY[next.kind]);
    }
    return () => window.clearTimeout(id);
  }, [transcript, active, inView, typed, shown, run]);

  // Keep the newest line in view inside the terminal (never scrolls the page)
  useEffect(() => {
    const screen = screenRef.current;
    if (screen) screen.scrollTop = screen.scrollHeight;
  }, [shown]);

  const finished = !!transcript && shown >= transcript.lines.length;
  const lines = transcript?.lines.slice(0, shown) ?? [];

  const [copied, setCopied] = useState(false);
  async function copyCommands() {
    try {
      await navigator.clipboard.writeText(FIRST_RUN);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  function replay() {
    setTyped(0);
    setShown(0);
    setRun((r) => r + 1);
  }

  return (
    <div className="term" ref={boxRef}>
      <div className="term-bar">
        <span className="term-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="term-title">~/{transcript?.repo ?? 'billing-api'}</span>
        <button type="button" className="code-copy-btn term-replay" onClick={replay} disabled={!finished}>
          Replay
        </button>
        <button
          type="button"
          className={`code-copy-btn${copied ? ' is-copied' : ''}`}
          onClick={copyCommands}
          aria-label="Copy the first-run commands"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
        <span className="visually-hidden" aria-live="polite">
          {copied ? 'First-run commands copied to clipboard' : ''}
        </span>
      </div>
      <pre className="term-screen" ref={screenRef} aria-hidden="true">
        <code>
          <span className="term-prompt">$ </span>
          <span className="tok-cmd">{COMMAND.slice(0, typed)}</span>
          {typed < COMMAND.length || !transcript ? <span className="term-caret" /> : '\n'}
          {lines.map((line, i) => (
            <span key={i} className={`term-line is-${line.kind}`}>
              {line.kind === 'hit' ? <span className="term-mark">+ </span> : null}
              {line.kind === 'yaml' ? highlightYamlLine(line.text) : line.text}
              {'\n'}
            </span>
          ))}
          {finished ? (
            <>
              <span className="term-prompt">$ </span>
              <span className="term-caret" />
            </>
          ) : null}
        </code>
      </pre>
      <p className="visually-hidden">
        Recorded run of <code>{COMMAND}</code> on the sample FastAPI repo.{' '}
        {transcript?.lines.map((l) => l.text).filter(Boolean).join('. ')}
      </p>
    </div>
  );
}
