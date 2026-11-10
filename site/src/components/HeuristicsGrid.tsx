import { HEURISTIC_CARDS } from '../data/siteData';

export function HeuristicsGrid() {
  return (
    <section id="heuristics" className="section">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">Deep Heuristic Matrix</span>
          <h2>Eight modular detectors. Zero guesswork.</h2>
          <p>
            Instead of checking a single manifest file, Heurix cross-references lockfiles, runtime version pins,
            Dockerfiles, Compose topologies, and environment templates into one Intermediate Representation.
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
