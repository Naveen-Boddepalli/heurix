import { HX_VERSION, REPO_URL } from '../data/siteData';
import { links } from '../lib/links';

const FOOTER_COLUMNS = [
  {
    title: 'Site',
    links: [
      { href: links.home, label: 'Home' },
      { href: links.playground, label: 'Playground' },
      { href: links.docs(), label: 'Docs' },
      { href: links.docs('changelog'), label: 'Changelog' },
    ],
  },
  {
    title: 'Docs',
    links: [
      { href: links.docs('getting-started'), label: 'Getting started' },
      { href: links.docs('cli-reference'), label: 'CLI reference' },
      { href: links.docs('configuration'), label: 'Configuration' },
      { href: links.docs('llms-txt'), label: 'llms.txt' },
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
          <p>Generates GitHub Actions, Dependabot, and Kubernetes config from your repo.</p>
          <p className="footer-meta">
            v{HX_VERSION} · MIT licensed ·{' '}
            <a href={REPO_URL} target="_blank" rel="noreferrer">
              Source on GitHub
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
