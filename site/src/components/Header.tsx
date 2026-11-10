import { useEffect, useRef, useState } from 'react';

const NAV_ITEMS = [
  { href: '#playground', label: 'Playground' },
  { href: '#heuristics', label: 'Heuristics' },
  { href: '#cli', label: 'CLI' },
  { href: '#docs', label: 'Docs' },
  { href: '#visibility', label: 'llms.txt' },
];

export function Header() {
  const [activeHash, setActiveHash] = useState('#playground');
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
          <span className="brand-badge">hx v0.1.0</span>
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

            <a
              href="https://github.com/Naveen-Boddepalli/heurix"
              className="icon-btn"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>

            <button
              type="button"
              className="icon-btn menu-button"
              {...({ popovertarget: 'mobile-site-menu', popovertargetaction: 'toggle' } as Record<string, string>)}
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
            {...({ popover: 'auto' } as Record<string, string>)}
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
