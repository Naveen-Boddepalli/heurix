export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container footer-inner">
        <div>
          <strong>Heurix (hx)</strong> — Deterministic Codebase Scanner &amp; YAML Synthesizer.
          <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBlockStart: '0.25rem' }}>
            MIT Licensed • Built for reproducible CI/CD and Kubernetes automation.
          </div>
        </div>

        <ul className="footer-links">
          <li>
            <a href="https://github.com/Naveen-Boddepalli/heurix" target="_blank" rel="noreferrer">
              GitHub
            </a>
          </li>
          <li>
            <a href="https://pypi.org/project/heurix/" target="_blank" rel="noreferrer">
              PyPI
            </a>
          </li>
          <li>
            <a href="llms.txt">llms.txt</a>
          </li>
          <li>
            <a href="llms-full.txt">llms-full.txt</a>
          </li>
          <li>
            <a href="robots.txt">robots.txt</a>
          </li>
        </ul>
      </div>
    </footer>
  );
}
