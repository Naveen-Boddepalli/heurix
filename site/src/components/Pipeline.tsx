import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { HEURISTIC_CARDS } from '../data/siteData';

/**
 * "How it works": repo files -> detectors -> generated files, drawn as a diagram you can
 * explore. Hover/focus (or tap) any chip to trace what it reads from and what it feeds.
 */

const FILES: { id: string; to: string[] }[] = [
  { id: '.python-version', to: ['versions'] },
  { id: 'uv.lock', to: ['lockfiles'] },
  { id: 'pnpm-lock.yaml', to: ['lockfiles'] },
  { id: 'docker-compose.yml', to: ['services'] },
  { id: '.env.example', to: ['secrets'] },
  { id: 'pnpm-workspace.yaml', to: ['monorepo'] },
  { id: 'Dockerfile', to: ['containers'] },
  { id: 'vercel.json', to: ['cloud'] },
];

const DETECTOR_OUTPUTS: Record<string, string[]> = {
  versions: ['ci'],
  lockfiles: ['ci', 'dependabot'],
  monorepo: ['ci', 'dependabot'],
  services: ['ci'],
  secrets: ['ci', 'k8s'],
  containers: ['k8s', 'dependabot'],
  cloud: ['ci'],
};

const OUTPUTS: { id: string; label: string }[] = [
  { id: 'ci', label: '.github/workflows/ci.yml' },
  { id: 'dependabot', label: '.github/dependabot.yml' },
  { id: 'k8s', label: 'k8s/*.yaml' },
];

const DETECTORS = HEURISTIC_CARDS.filter((c) => c.id in DETECTOR_OUTPUTS).map((c) => ({ id: c.id, label: c.title }));

type NodeKey = `f:${string}` | `d:${string}` | `o:${string}`;
interface Edge {
  from: NodeKey;
  to: NodeKey;
  stage: 0 | 1;
}

const EDGES: Edge[] = [
  ...FILES.flatMap((f) => f.to.map((d) => ({ from: `f:${f.id}` as NodeKey, to: `d:${d}` as NodeKey, stage: 0 as const }))),
  ...Object.entries(DETECTOR_OUTPUTS).flatMap(([d, outs]) =>
    outs.map((o) => ({ from: `d:${d}` as NodeKey, to: `o:${o}` as NodeKey, stage: 1 as const }))
  ),
];

const edgeKey = (e: Edge) => `${e.from}>${e.to}`;

function labelOf(key: NodeKey) {
  const id = key.slice(2);
  if (key.startsWith('d:')) return DETECTORS.find((d) => d.id === id)?.label ?? id;
  if (key.startsWith('o:')) return OUTPUTS.find((o) => o.id === id)?.label ?? id;
  return id;
}

/** The chain through one node: upstream edges into it, downstream edges out of it, one hop beyond detectors. */
function traceFrom(key: NodeKey) {
  const nodes = new Set<NodeKey>([key]);
  const edges = new Set<string>();
  const take = (e: Edge) => {
    edges.add(edgeKey(e));
    nodes.add(e.from);
    nodes.add(e.to);
  };
  if (key.startsWith('f:')) {
    for (const e of EDGES.filter((e) => e.from === key)) {
      take(e);
      EDGES.filter((x) => x.from === e.to).forEach(take);
    }
  } else if (key.startsWith('d:')) {
    EDGES.filter((e) => e.from === key || e.to === key).forEach(take);
  } else {
    for (const e of EDGES.filter((e) => e.to === key)) {
      take(e);
      EDGES.filter((x) => x.to === e.from).forEach(take);
    }
  }
  return { nodes, edges };
}

function describe(key: NodeKey | null) {
  if (!key) return 'Hover or tap any item to trace it.';
  const { nodes } = traceFrom(key);
  const pick = (p: string) => [...nodes].filter((n) => n.startsWith(p)).map((n) => labelOf(n as NodeKey));
  const files = pick('f:');
  const dets = pick('d:');
  const outs = pick('o:');
  return `${files.join(', ')}  →  ${dets.join(', ')}  →  ${outs.join(', ')}`;
}

export function Pipeline() {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [hovered, setHovered] = useState<NodeKey | null>(null);
  const [pinned, setPinned] = useState<NodeKey | null>(null);
  const focus = hovered ?? pinned;
  const trace = useMemo(() => (focus ? traceFrom(focus) : null), [focus]);

  // Connector geometry from the live chip positions
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const measure = () => {
      // Layout offsets (not getBoundingClientRect) so the chips' entrance translate doesn't skew the lines
      const rectOf = (key: NodeKey) => {
        const el = box.querySelector<HTMLElement>(`[data-node="${CSS.escape(key)}"]`);
        if (!el) return null;
        let left = 0;
        let top = 0;
        for (let n: HTMLElement | null = el; n && n !== box; n = n.offsetParent as HTMLElement | null) {
          left += n.offsetLeft;
          top += n.offsetTop;
        }
        return { left, top, right: left + el.offsetWidth, height: el.offsetHeight };
      };
      const next: Record<string, string> = {};
      for (const e of EDGES) {
        const a = rectOf(e.from);
        const b = rectOf(e.to);
        if (!a || !b) continue;
        const x1 = a.right;
        const y1 = a.top + a.height / 2;
        const x2 = b.left;
        const y2 = b.top + b.height / 2;
        const dx = Math.max(24, (x2 - x1) * 0.5);
        next[edgeKey(e)] = `M${x1.toFixed(1)} ${y1.toFixed(1)} C${(x1 + dx).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
      }
      setPaths(next);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, []);

  const chipProps = (key: NodeKey, col: number, row: number) => ({
    type: 'button' as const,
    'data-node': key,
    className: `pipe-chip${trace?.nodes.has(key) ? ' is-on' : ''}`,
    style: { '--col': col, '--row': row } as React.CSSProperties,
    'aria-pressed': pinned === key,
    onMouseEnter: () => setHovered(key),
    onMouseLeave: () => setHovered(null),
    onFocus: () => setHovered(key),
    onBlur: () => setHovered(null),
    onClick: () => setPinned((p) => (p === key ? null : key)),
  });

  return (
    <section id="how-it-works" className="section">
      <div className="container">
        <div className="section-header reveal">
          <h2>How it works</h2>
          <p>
            Each file hx reads goes to a detector, and each detector feeds one or more generated files. Nothing else
            goes in, so the same repo always gives the same YAML.
          </p>
        </div>

        {/* Focus state lives in a data attribute: className is shared with useReveal's is-visible */}
        <div className="pipeline reveal" data-focus={focus ? '' : undefined} ref={boxRef}>
          <svg className="pipeline-links" aria-hidden="true">
            {EDGES.map((e, i) => {
              const d = paths[edgeKey(e)];
              if (!d) return null;
              const on = trace?.edges.has(edgeKey(e));
              return (
                <g key={edgeKey(e)} className={on ? 'is-on' : undefined} style={{ '--d': e.stage * 450 + i * 18 } as React.CSSProperties}>
                  <path className="pipe-link" d={d} pathLength={1} />
                  {on ? <path className="pipe-flow" d={d} /> : null}
                </g>
              );
            })}
          </svg>

          <div className="pipeline-col">
            <h3 className="pipeline-title">Your repo</h3>
            <div className="pipeline-chips">
            {FILES.map((f, row) => (
              <button key={f.id} {...chipProps(`f:${f.id}`, 0, row)}>
                {f.id}
              </button>
            ))}
            </div>
          </div>
          <div className="pipeline-col">
            <h3 className="pipeline-title">Detectors</h3>
            <div className="pipeline-chips">
            {DETECTORS.map((d, row) => (
              <button key={d.id} {...chipProps(`d:${d.id}`, 1, row)}>
                {d.label}
              </button>
            ))}
            </div>
          </div>
          <div className="pipeline-col">
            <h3 className="pipeline-title">Generated</h3>
            <div className="pipeline-chips">
            {OUTPUTS.map((o, row) => (
              <button key={o.id} {...chipProps(`o:${o.id}`, 2, row)}>
                {o.label}
              </button>
            ))}
            </div>
          </div>
        </div>

        <p className="pipeline-trace" aria-live="polite">
          {describe(focus)}
        </p>
      </div>
    </section>
  );
}
