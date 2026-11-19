import { useState } from 'react';
import { RELEASES, REPO_URL } from '../data/siteData';

export function WhatsNew() {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? RELEASES : RELEASES.slice(0, 2);

  return (
    <section id="changelog" className="section" aria-labelledby="changelog-title">
      <div className="container">
        <div className="section-header">
          <h2 id="changelog-title">Changelog</h2>
          <p>
            To upgrade, re-run <code>hx generate</code>, read the list of values it says it will replace, then run{' '}
            <code>hx check</code>.
          </p>
        </div>

        <ol className="release-list">
          {visible.map((rel, idx) => (
            <li key={rel.version} className="release-card">
              <header className="release-head">
                <div className="release-version">
                  <span className="release-tag">v{rel.version}</span>
                  {idx === 0 && <span className="new-badge">latest</span>}
                </div>
                <h3>{rel.headline}</h3>
                <time dateTime={rel.date}>
                  {new Date(`${rel.date}T00:00:00Z`).toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    timeZone: 'UTC',
                  })}
                </time>
              </header>
              <div className="release-groups">
                {rel.groups.map((g) => (
                  <div key={g.label} className="release-group">
                    <span className={`release-group-label is-${g.tone}`}>{g.label}</span>
                    <ul>
                      {g.items.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </li>
          ))}
        </ol>

        <div className="release-actions">
          {RELEASES.length > 2 && (
            <button type="button" className="btn" onClick={() => setShowAll((v) => !v)} aria-expanded={showAll}>
              {showAll ? 'Show fewer releases' : `Show all ${RELEASES.length} releases`}
            </button>
          )}
          <a className="btn" href={`${REPO_URL}/blob/main/CHANGELOG.md`} target="_blank" rel="noreferrer">
            Full CHANGELOG.md
          </a>
        </div>
      </div>
    </section>
  );
}
