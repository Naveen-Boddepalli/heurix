import { useEffect } from 'react';

/**
 * Fades `.reveal` elements in the first time they scroll into view.
 *
 * One shared IntersectionObserver per page; a MutationObserver picks up elements that
 * React renders later (playground panels, docs sections). Content stays visible when
 * JS or IntersectionObserver is unavailable, because the hidden start state only
 * applies under `html.js-reveal`.
 */
export function useReveal() {
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const root = document.documentElement;
    root.classList.add('js-reveal');

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 }
    );

    const scan = (scope: ParentNode) => {
      scope.querySelectorAll('.reveal:not(.is-visible)').forEach((el) => io.observe(el));
    };
    scan(document);

    const mo = new MutationObserver((records) => {
      for (const r of records) {
        r.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          if (node.matches('.reveal:not(.is-visible)')) io.observe(node);
          scan(node);
        });
      }
    });
    const main = document.querySelector('main') ?? document.body;
    mo.observe(main, { childList: true, subtree: true });

    return () => {
      io.disconnect();
      mo.disconnect();
      root.classList.remove('js-reveal');
    };
  }, []);
}
