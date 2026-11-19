import { useEffect } from 'react';

/**
 * Page-wide backdrop: a faint dot grid plus a soft accent glow that follows the pointer.
 * Pure CSS apart from one rAF-throttled pointermove listener that writes --mx/--my on <html>.
 */
export function BackgroundField() {
  useEffect(() => {
    const root = document.documentElement;
    let frame = 0;
    let x = 0;
    let y = 0;

    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse' && e.pointerType !== 'pen') return;
      x = e.clientX;
      y = e.clientY;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        root.style.setProperty('--mx', `${x}px`);
        root.style.setProperty('--my', `${y}px`);
        root.classList.add('has-pointer');
      });
    };
    const onLeave = () => root.classList.remove('has-pointer');

    window.addEventListener('pointermove', onMove, { passive: true });
    document.documentElement.addEventListener('pointerleave', onLeave);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', onMove);
      document.documentElement.removeEventListener('pointerleave', onLeave);
    };
  }, []);

  return (
    <div className="bg-field" aria-hidden="true">
      <div className="bg-dots" />
      <div className="bg-glow" />
    </div>
  );
}
