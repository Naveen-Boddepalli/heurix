/**
 * Theme switch as a "regenerate": the page is rewritten in the new theme line by line,
 * the way hx rewrites a YAML file. Horizontal bands wipe across from the toggle's side,
 * staggered top to bottom, each with an accent caret on its leading edge.
 *
 * Mechanics: inside a view transition, the new snapshot is clipped to the written part of
 * each band and the old snapshot to what's left, a few px further on. The gap between the
 * two shows the image-pair's accent background, which reads as a caret per line.
 */

const BAND_PX = 46;
const MAX_BANDS = 24;
const BAND_MS = 340;
const SPREAD_MS = 320;
const FRAMES = 40;
const CARET_PX = 3;

const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function buildFrames(width: number, height: number, fromRight: boolean) {
  const bands = Math.min(MAX_BANDS, Math.max(6, Math.ceil(height / BAND_PX)));
  const bandH = height / bands;
  const stagger = SPREAD_MS / (bands - 1);
  const duration = BAND_MS + SPREAD_MS;
  const fx = (x: number) => (fromRight ? width - x : x).toFixed(1);
  const fy = (y: number) => y.toFixed(1);

  const newFrames: string[] = [];
  const oldFrames: string[] = [];

  for (let f = 0; f < FRAMES; f++) {
    const t = (f / (FRAMES - 1)) * duration;
    const written: number[] = [];
    const caret: number[] = [];
    for (let i = 0; i < bands; i++) {
      const local = Math.min(1, Math.max(0, (t - i * stagger) / BAND_MS));
      written.push(easeInOutCubic(local) * width);
      // The caret only shows while its line is being written
      caret.push(Math.sin(Math.PI * local) * CARET_PX);
    }

    // Written region: from the start edge out to each band's progress (2 * bands + 2 points)
    const np: string[] = [`${fx(0)}px 0px`];
    const op: string[] = [`${fx(width)}px 0px`];
    for (let i = 0; i < bands; i++) {
      const y0 = i * bandH;
      const y1 = i === bands - 1 ? height : (i + 1) * bandH;
      np.push(`${fx(written[i])}px ${fy(y0)}px`, `${fx(written[i])}px ${fy(y1)}px`);
      const ox = Math.min(width, written[i] + caret[i]);
      op.push(`${fx(ox)}px ${fy(y0)}px`, `${fx(ox)}px ${fy(y1)}px`);
    }
    np.push(`${fx(0)}px ${fy(height)}px`);
    op.push(`${fx(width)}px ${fy(height)}px`);
    newFrames.push(`polygon(${np.join(', ')})`);
    oldFrames.push(`polygon(${op.join(', ')})`);
  }

  return { newFrames, oldFrames, duration };
}

/** Run inside an active theme view transition, after `transition.ready`. */
export function playThemeRewrite(fromRight: boolean) {
  const root = document.documentElement;
  const { newFrames, oldFrames, duration } = buildFrames(window.innerWidth, window.innerHeight, fromRight);
  const timing: KeyframeAnimationOptions = { duration, easing: 'linear', fill: 'both' };
  root.animate({ clipPath: newFrames }, { ...timing, pseudoElement: '::view-transition-new(root)' });
  root.animate({ clipPath: oldFrames }, { ...timing, pseudoElement: '::view-transition-old(root)' });
}
