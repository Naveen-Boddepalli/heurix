import { useEffect, useRef, useState } from 'react';
import { HX_VERSION, REPO_URL } from '../data/siteData';

const NAV_ITEMS = [
  { href: '#playground', label: 'Playground' },
  { href: '#heuristics', label: 'Heuristics' },
  { href: '#cli', label: 'CLI' },
  { href: '#config', label: 'Config' },
  { href: '#changelog', label: "What's new" },
  { href: '#docs', label: 'Docs' },
  { href: '#visibility', label: 'AI' },
];

export function Header() {
  const [activeHash, setActiveHash] = useState('');
  const [hiddenOnScroll, setHiddenOnScroll] = useState(false);
  const headerRef = useRef<HTMLElement | null>(null);

  // Sync active navigation hash
  useEffect(() => {
    const syncHash = () => {
      if (window.location.hash) {
        setActiveHash(window.location.hash);
      }
    };
    syncHash();
    window.addEventListener('hashchange', syncHash);
    return () => window.removeEventListener('hashchange', syncHash);
  }, []);

  // Scroll-spy: highlight the nav item for the section currently in view
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const sections = NAV_ITEMS.map((item) => document.querySelector<HTMLElement>(item.href)).filter(
      (el): el is HTMLElement => el !== null
    );
    const visible = new Map<string, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.set(`#${entry.target.id}`, entry.boundingClientRect.top);
          else visible.delete(`#${entry.target.id}`);
        }
        if (visible.size === 0) return;
        const [top] = [...visible.entries()].sort((a, b) => Math.abs(a[1]) - Math.abs(b[1]));
        setActiveHash(top[0]);
      },
      { rootMargin: '-35% 0px -55% 0px' }
    );
    sections.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  // Fallback for browsers without scroll-state container queries
  useEffect(() => {
    if (typeof CSS !== 'undefined' && CSS.supports('container-type', 'scroll-state')) {
      return;
    }
    let lastY = window.scrollY;
    const onScroll = () => {
      const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      const y = Math.max(0, Math.min(window.scrollY, maxScroll));
      if (y === lastY) return;
      const barHeight = headerRef.current?.offsetHeight ?? 60;
      setHiddenOnScroll(y > lastY && y > barHeight);
      lastY = y;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Keep <meta name="color-scheme"> synchronized across tabs via storage event
  useEffect(() => {
    const applyStoredTheme = () => {
      const meta = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
      if (!meta) return;
      try {
        const stored = localStorage.getItem('color-scheme');
        meta.content = stored === 'light' || stored === 'dark' ? stored : 'light dark';
      } catch {
        meta.content = 'light dark';
      }
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'color-scheme' || e.key === null) {
        applyStoredTheme();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  function handleThemeToggle() {
    const meta = document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]');
    if (!meta) return;

    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const systemTheme = systemDark ? 'dark' : 'light';

    let stored: string | null = null;
    try {
      stored = localStorage.getItem('color-scheme');
    } catch {
      stored = meta.content === 'light' || meta.content === 'dark' ? meta.content : null;
    }

    const currentRendered = stored === 'light' || stored === 'dark' ? stored : systemTheme;
    const targetTheme = currentRendered === 'dark' ? 'light' : 'dark';

    try {
      if (targetTheme === systemTheme) {
        localStorage.removeItem('color-scheme');
        meta.content = 'light dark';
      } else {
        localStorage.setItem('color-scheme', targetTheme);
        meta.content = targetTheme;
      }
    } catch {
      meta.content = targetTheme === systemTheme ? 'light dark' : targetTheme;
    }
  }

  return (
    <header ref={headerRef} className={`site-header${hiddenOnScroll ? ' is-hidden' : ''}`}>
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <div className="container header-inner">
        <a href="#top" className="brand-link" aria-label="Heurix home">
          <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#0f172a" />
            <path
              d="M16 4.5L26 10.25V21.75L16 27.5L6 21.75V10.25L16 4.5Z"
              stroke="#22d3ee"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            <path
              d="M11 11.5V20.5M11 16H16M16 11.5V20.5"
              stroke="#f8fafc"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M19.5 13.5L23 19.5M23 13.5L19.5 19.5"
              stroke="#22d3ee"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          <span>Heurix</span>
          <span className="brand-badge">hx v{HX_VERSION}</span>
        </a>

        <div className="header-spacer" />

        <nav className="site-nav" aria-label="Primary">
          <ul className="nav-links">
            {NAV_ITEMS.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  aria-current={activeHash === item.href ? 'page' : undefined}
                  onClick={() => setActiveHash(item.href)}
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>

          <div className="header-actions">
            <button
              type="button"
              className="icon-btn theme-toggle"
              onClick={handleThemeToggle}
              aria-label="Toggle color scheme"
            >
              <span className="theme-label-dark">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
                <span>Dark</span>
              </span>
              <span className="theme-label-light">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41m11.32-11.32l1.41-1.41" />
                </svg>
                <span>Light</span>
              </span>
            </button>

            <a href={REPO_URL} className="icon-btn" target="_blank" rel="noreferrer" aria-label="Heurix on GitHub">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.53-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
              </svg>
              <span className="github-label">GitHub</span>
            </a>

            <button
              type="button"
              className="icon-btn menu-button"
              aria-label="Open menu"
              popoverTarget="mobile-site-menu"
              popoverTargetAction="toggle"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M4 6h16M4 12h16M4 18h16" />
              </svg>
              <span>Menu</span>
            </button>
          </div>

          <div
            id="mobile-site-menu"
            className="mobile-menu"
            popover="auto"
          >
            <ul className="mobile-menu-list">
              {NAV_ITEMS.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    aria-current={activeHash === item.href ? 'page' : undefined}
                    onClick={() => {
                      setActiveHash(item.href);
                      const el = document.getElementById('mobile-site-menu') as HTMLElement & {
                        hidePopover?: () => void;
                      };
                      el?.hidePopover?.();
                    }}
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </nav>
      </div>
    </header>
  );
}
