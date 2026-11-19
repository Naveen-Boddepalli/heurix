import { HOW_IT_WORKS } from '../data/siteData';

export function HowItWorks() {
  return (
    <section id="how-it-works" className="section section-tight" aria-labelledby="how-it-works-title">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">How it works</span>
          <h2 id="how-it-works-title">One pipeline, four commands</h2>
          <p>
            Detectors never write files, and synthesizers never read the repo. Everything flows through one typed
            Intermediate Representation, so the same inputs always produce the same YAML.
          </p>
        </div>

        <ol className="flow-grid">
          {HOW_IT_WORKS.map((item) => (
            <li key={item.step} className="flow-card">
              <div className="flow-card-top">
                <span className="flow-step" aria-hidden="true">
                  {item.step}
                </span>
                <code className="flow-cmd">{item.cmd}</code>
              </div>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
