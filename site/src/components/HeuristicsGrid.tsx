import { HEURISTIC_CARDS } from '../data/siteData';

export function HeuristicsGrid() {
  return (
    <section id="heuristics" className="section">
      <div className="container">
        <div className="section-header">
          <h2>What it detects</h2>
          <p>
            Each detector looks at a specific set of files. Their results go into one project description (run{' '}
            <code>hx scan</code> to see it), and the generators work only from that.
          </p>
        </div>

        <div className="cards-grid">
          {HEURISTIC_CARDS.map((card) => (
            <article key={card.id} className="heuristic-card">
              <header className="card-meta-top">
                <h3>{card.title}</h3>
                <span className="card-tag">{card.detector}</span>
              </header>
              <p style={{ fontSize: '0.9375rem' }}>{card.summary}</p>
              <ul className="signal-list" aria-label={`${card.title} trigger signals`}>
                {card.signals.map((sig) => (
                  <li key={sig}>{sig}</li>
                ))}
              </ul>
              <footer className="card-output-foot">{card.output}</footer>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
