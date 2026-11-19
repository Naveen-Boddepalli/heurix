import { useEffect, useLayoutEffect, type RefObject } from 'react';
import { prefersReducedMotion } from './useReducedMotion';

const finePointer = () => typeof window !== 'undefined' && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

/**
 * Writes the pointer position relative to each matching element as --x / --y (px),
 * for CSS spotlight effects. One delegated listener on the container.
 */
export function usePointerVars(containerRef: RefObject<HTMLElement | null>, selector: string) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !finePointer()) return;
    let frame = 0;
    let evt: PointerEvent | null = null;
    const onMove = (e: PointerEvent) => {
      evt = e;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!evt) return;
        const target = (evt.target as Element | null)?.closest<HTMLElement>(selector);
        if (!target || !container.contains(target)) return;
        const rect = target.getBoundingClientRect();
        target.style.setProperty('--x', `${evt.clientX - rect.left}px`);
        target.style.setProperty('--y', `${evt.clientY - rect.top}px`);
      });
    };
    container.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      container.removeEventListener('pointermove', onMove);
    };
  }, [containerRef, selector]);
}

/** Small magnetic pull toward the pointer (max ±strength px). Fine pointers only, off under reduced motion. */
export function useMagnetic(containerRef: RefObject<HTMLElement | null>, selector: string, strength = 4) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !finePointer() || prefersReducedMotion()) return;
    const els = Array.from(container.querySelectorAll<HTMLElement>(selector));
    const cleanups = els.map((el) => {
      const onMove = (e: PointerEvent) => {
        const r = el.getBoundingClientRect();
        const dx = (e.clientX - (r.left + r.width / 2)) / (r.width / 2);
        const dy = (e.clientY - (r.top + r.height / 2)) / (r.height / 2);
        el.style.translate = `${(dx * strength).toFixed(2)}px ${(dy * strength).toFixed(2)}px`;
      };
      const onLeave = () => {
        el.style.translate = '';
      };
      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerleave', onLeave);
      return () => {
        el.removeEventListener('pointermove', onMove);
        el.removeEventListener('pointerleave', onLeave);
      };
    });
    return () => cleanups.forEach((c) => c());
  }, [containerRef, selector, strength]);
}

/**
 * Positions a sliding indicator under the selected tab of a tablist by writing
 * --ind-x / --ind-w on the list. Re-measures on resize.
 */
export function useTabIndicator(listRef: RefObject<HTMLElement | null>, activeKey: string) {
  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const measure = () => {
      const active = list.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
      if (!active) return;
      list.style.setProperty('--ind-x', `${active.offsetLeft}px`);
      list.style.setProperty('--ind-w', `${active.offsetWidth}px`);
      list.classList.add('has-indicator');
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(list);
    return () => ro.disconnect();
  }, [listRef, activeKey]);
}
