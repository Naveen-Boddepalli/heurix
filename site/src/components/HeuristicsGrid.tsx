import { useRef } from 'react';
import { HEURISTIC_CARDS } from '../data/siteData';
import { usePointerVars } from '../lib/usePointerVars';

export function HeuristicsGrid() {
  const gridRef = useRef<HTMLDivElement | null>(null);
  usePointerVars(gridRef, '.heuristic-card');

  return (
    <section id="heuristics" className="section">
      <div className="container">
        <div className="section-header reveal">
          <h2>What it detects</h2>
          <p>
            Each detector looks at a specific set of files. Their results go into one project description (run{' '}
            <code>hx scan</code> to see it), and the generators work only from that.
          </p>
        </div>

        <div className="cards-grid" ref={gridRef}>
          {HEURISTIC_CARDS.map((card, i) => (
            <article
              key={card.id}
              className="heuristic-card reveal"
              style={{ '--i': i % 3 } as React.CSSProperties}
            >
              <header className="card-meta-top">
                <h3>{card.title}</h3>
                <span className="card-tag">{card.detector}</span>
              </header>
              <p style={{ fontSize: '0.9375rem' }}>{card.summary}</p>
              <ul className="signal-list" aria-label={`${card.title} trigger signals`}>
                {card.signals.map((sig, j) => (
                  <li key={sig} style={{ '--j': j } as React.CSSProperties}>
                    {sig}
                  </li>
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
