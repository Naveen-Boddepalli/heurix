import { useEffect, useRef } from 'react';
import { prefersReducedMotion } from '../lib/useReducedMotion';

/**
 * Hero backdrop: a slowly drifting "dependency graph". Labelled file nodes (lockfiles,
 * Dockerfiles, version pins) periodically send a pulse hop-by-hop toward a generated
 * YAML node, which is what hx does, drawn as a picture.
 *
 * Capped at 30 fps, paused off screen / in hidden tabs, one static frame under reduced motion.
 */

type Kind = 'dot' | 'file' | 'out';
interface GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  kind: Kind;
  label?: string;
  flash: number;
}
interface Pulse {
  path: number[];
  seg: number;
  t: number;
}

const FILE_LABELS = ['pyproject.toml', 'uv.lock', 'Dockerfile', '.nvmrc', 'go.mod', 'compose.yaml', '.env.example', 'pnpm-lock.yaml'];
const OUT_LABELS = ['ci.yml', 'dependabot.yml', 'deployment.yaml'];
const LINK_DIST = 140;
const POINTER_DIST = 170;
const FRAME_MS = 1000 / 30;

function rgba(rgb: string, a: number) {
  // rgb is "rgb(r, g, b)" from getComputedStyle; turn it into rgba with the given alpha
  const m = rgb.match(/[\d.]+/g);
  if (!m) return `rgba(127,127,127,${a})`;
  return `rgba(${m[0]}, ${m[1]}, ${m[2]}, ${a})`;
}

export function HeroGraph() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const reduced = prefersReducedMotion();
    let width = 0;
    let height = 0;
    let nodes: GraphNode[] = [];
    let pulses: Pulse[] = [];
    let accent = 'rgb(56, 189, 248)';
    let ink = 'rgb(148, 163, 184)';
    let pointer: { x: number; y: number } | null = null;
    let running = false;
    let visible = true;
    let raf = 0;
    let last = 0;
    let sincePulse = 0;

    // Resolve theme colors through the canvas's own CSS (color / outline-color are set to tokens)
    const readColors = () => {
      const cs = getComputedStyle(canvas);
      accent = cs.color;
      ink = cs.outlineColor;
    };

    const seed = () => {
      const count = Math.round(Math.min(48, Math.max(18, (width * height) / 22000)));
      const labels: { kind: Kind; label: string }[] = [
        ...FILE_LABELS.slice(0, width < 640 ? 4 : FILE_LABELS.length).map((label) => ({ kind: 'file' as Kind, label })),
        ...OUT_LABELS.slice(0, width < 640 ? 2 : OUT_LABELS.length).map((label) => ({ kind: 'out' as Kind, label })),
      ];
      nodes = Array.from({ length: count }, (_, i) => {
        const tag = labels[i];
        // Files start on the left, outputs on the right, so pulses read left-to-right
        const xBias = tag?.kind === 'file' ? 0.05 + Math.random() * 0.35 : tag?.kind === 'out' ? 0.65 + Math.random() * 0.3 : Math.random();
        const speed = 0.12 + Math.random() * 0.18;
        const angle = Math.random() * Math.PI * 2;
        return {
          x: xBias * width,
          y: Math.random() * height,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          r: tag ? 2.6 : 1.2 + Math.random() * 1.1,
          kind: tag?.kind ?? 'dot',
          label: tag?.label,
          flash: 0,
        };
      });
      pulses = [];
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const changed = Math.abs(rect.width - width) > 40 || Math.abs(rect.height - height) > 40;
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (changed || nodes.length === 0) seed();
      draw();
    };

    // Greedy walk from a file node toward the nearest output node over current proximity links
    const spawnPulse = () => {
      const files = nodes.map((n, i) => (n.kind === 'file' ? i : -1)).filter((i) => i >= 0);
      const outs = nodes.map((n, i) => (n.kind === 'out' ? i : -1)).filter((i) => i >= 0);
      if (!files.length || !outs.length) return;
      const start = files[Math.floor(Math.random() * files.length)];
      const s = nodes[start];
      const target = outs.reduce((best, i) =>
        Math.hypot(nodes[i].x - s.x, nodes[i].y - s.y) < Math.hypot(nodes[best].x - s.x, nodes[best].y - s.y) ? i : best
      );
      const path = [start];
      const seen = new Set(path);
      let cur = start;
      for (let hop = 0; hop < 9 && cur !== target; hop++) {
        const c = nodes[cur];
        const t = nodes[target];
        let next = -1;
        let bestDist = Math.hypot(t.x - c.x, t.y - c.y);
        nodes.forEach((n, i) => {
          if (seen.has(i) || Math.hypot(n.x - c.x, n.y - c.y) > LINK_DIST * 1.25) return;
          const d = Math.hypot(t.x - n.x, t.y - n.y);
          if (d < bestDist) {
            bestDist = d;
            next = i;
          }
        });
        if (next === -1) break;
        path.push(next);
        seen.add(next);
        cur = next;
      }
      if (path.length >= 3) pulses.push({ path, seg: 0, t: 0 });
    };

    const step = () => {
      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 8 || n.x > width - 8) n.vx *= -1;
        if (n.y < 8 || n.y > height - 8) n.vy *= -1;
        n.x = Math.max(8, Math.min(width - 8, n.x));
        n.y = Math.max(8, Math.min(height - 8, n.y));
        n.flash *= 0.94;
      }
      sincePulse += FRAME_MS;
      if (sincePulse > 1800 && pulses.length < 3) {
        sincePulse = 0;
        spawnPulse();
      }
      pulses = pulses.filter((p) => {
        p.t += 0.07;
        if (p.t >= 1) {
          p.t = 0;
          p.seg += 1;
          nodes[p.path[p.seg]].flash = Math.max(nodes[p.path[p.seg]].flash, 0.6);
          if (p.seg >= p.path.length - 1) {
            nodes[p.path[p.path.length - 1]].flash = 1;
            return false;
          }
        }
        return true;
      });
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      // Links between nearby nodes
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d > LINK_DIST) continue;
          ctx.strokeStyle = rgba(ink, (1 - d / LINK_DIST) * 0.22);
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      // Pointer links
      if (pointer) {
        for (const n of nodes) {
          const d = Math.hypot(n.x - pointer.x, n.y - pointer.y);
          if (d > POINTER_DIST) continue;
          ctx.strokeStyle = rgba(accent, (1 - d / POINTER_DIST) * 0.35);
          ctx.beginPath();
          ctx.moveTo(pointer.x, pointer.y);
          ctx.lineTo(n.x, n.y);
          ctx.stroke();
        }
      }

      // Pulse trails
      for (const p of pulses) {
        ctx.strokeStyle = rgba(accent, 0.45);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(nodes[p.path[0]].x, nodes[p.path[0]].y);
        for (let k = 1; k <= p.seg; k++) ctx.lineTo(nodes[p.path[k]].x, nodes[p.path[k]].y);
        const a = nodes[p.path[p.seg]];
        const b = nodes[p.path[p.seg + 1]];
        const hx = a.x + (b.x - a.x) * p.t;
        const hy = a.y + (b.y - a.y) * p.t;
        ctx.lineTo(hx, hy);
        ctx.stroke();
        ctx.fillStyle = rgba(accent, 0.25);
        ctx.beginPath();
        ctx.arc(hx, hy, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = rgba(accent, 0.95);
        ctx.beginPath();
        ctx.arc(hx, hy, 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.lineWidth = 1;

      // Nodes and labels
      ctx.font = '500 11px ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.textBaseline = 'middle';
      for (const n of nodes) {
        const near = pointer ? Math.max(0, 1 - Math.hypot(n.x - pointer.x, n.y - pointer.y) / POINTER_DIST) : 0;
        const glow = Math.max(near, n.flash);
        if (n.flash > 0.05) {
          ctx.strokeStyle = rgba(accent, n.flash * 0.6);
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r + 4 + (1 - n.flash) * 10, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.fillStyle = n.kind === 'dot' ? rgba(ink, 0.35 + glow * 0.5) : rgba(accent, 0.55 + glow * 0.45);
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + glow * 1.2, 0, Math.PI * 2);
        ctx.fill();
        // Labels surface only when a node is lit (pointer nearby or a pulse passing), so they never sit on the copy
        if (n.label && glow > 0.08) {
          ctx.fillStyle = n.kind === 'out' ? rgba(accent, glow * 0.95) : rgba(ink, glow * 0.9);
          ctx.fillText(n.label, n.x + 7, n.y);
        }
      }
    };

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (now - last < FRAME_MS) return;
      last = now;
      step();
      draw();
    };

    const sync = () => {
      const shouldRun = !reduced && visible && document.visibilityState === 'visible';
      if (shouldRun && !running) {
        running = true;
        last = 0;
        raf = requestAnimationFrame(loop);
      } else if (!shouldRun && running) {
        running = false;
        cancelAnimationFrame(raf);
      }
    };

    const onPointer = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse' && e.pointerType !== 'pen') return;
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      pointer = x >= 0 && y >= 0 && x <= rect.width && y <= rect.height ? { x, y } : null;
      if (reduced) draw();
    };
    const onPointerOut = () => {
      pointer = null;
    };

    readColors();
    resize();

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      sync();
    });
    io.observe(canvas);

    // Re-read colors when the theme flips (meta toggle or OS setting)
    const meta = document.querySelector('meta[name="color-scheme"]');
    const mo = new MutationObserver(() => requestAnimationFrame(() => (readColors(), draw())));
    if (meta) mo.observe(meta, { attributes: true, attributeFilter: ['content'] });
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const onScheme = () => (readColors(), draw());
    mql.addEventListener('change', onScheme);

    document.addEventListener('visibilitychange', sync);
    window.addEventListener('pointermove', onPointer, { passive: true });
    document.documentElement.addEventListener('pointerleave', onPointerOut);
    sync();

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      mo.disconnect();
      mql.removeEventListener('change', onScheme);
      document.removeEventListener('visibilitychange', sync);
      window.removeEventListener('pointermove', onPointer);
      document.documentElement.removeEventListener('pointerleave', onPointerOut);
    };
  }, []);

  return <canvas ref={canvasRef} className="hero-graph" aria-hidden="true" />;
}
