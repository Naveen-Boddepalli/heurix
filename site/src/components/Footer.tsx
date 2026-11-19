import { HX_VERSION, REPO_URL } from '../data/siteData';

const FOOTER_COLUMNS = [
  {
    title: 'Product',
    links: [
      { href: '#playground', label: 'Playground' },
      { href: '#heuristics', label: 'Heuristics' },
      { href: '#cli', label: 'CLI' },
      { href: '#config', label: 'Configuration' },
    ],
  },
  {
    title: 'Resources',
    links: [
      { href: '#docs', label: 'Documentation' },
      { href: '#changelog', label: 'Release notes' },
      { href: 'llms.txt', label: 'llms.txt' },
      { href: 'llms-full.txt', label: 'llms-full.txt' },
    ],
  },
  {
    title: 'Get hx',
    links: [
      { href: REPO_URL, label: 'GitHub', external: true },
      { href: 'https://pypi.org/project/heurix/', label: 'PyPI', external: true },
      { href: 'https://github.com/Naveen-Boddepalli/heurix/pkgs/container/heurix', label: 'Docker image', external: true },
      { href: `${REPO_URL}/issues`, label: 'Report an issue', external: true },
    ],
  },
];

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container footer-inner">
        <div className="footer-brand">
          <strong>Heurix (hx)</strong>
          <p>Deterministic codebase scanner &amp; YAML synthesizer for CI/CD, Dependabot, and Kubernetes.</p>
          <p className="footer-meta">
            v{HX_VERSION} · MIT licensed ·{' '}
            <a href={`${REPO_URL}/blob/main/CHANGELOG.md`} target="_blank" rel="noreferrer">
              Changelog
            </a>
          </p>
        </div>

        {FOOTER_COLUMNS.map((col) => (
          <nav key={col.title} className="footer-col" aria-label={col.title}>
            <h2 className="footer-col-title">{col.title}</h2>
            <ul className="footer-links">
              {col.links.map((link) => (
                <li key={link.label}>
                  <a
                    href={link.href}
                    {...('external' in link && link.external ? { target: '_blank', rel: 'noreferrer' } : {})}
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
    </footer>
  );
}
