import { CliExamples } from '../components/CliExamples';
import { ComparisonTable } from '../components/ComparisonTable';
import { Hero } from '../components/Hero';
import { HeuristicsGrid } from '../components/HeuristicsGrid';
import { links } from '../lib/links';
import { mountPage } from './PageShell';

mountPage(
  'home',
  <>
    <Hero />
    <HeuristicsGrid />
    <CliExamples />
    <ComparisonTable />
    <section className="section">
      <div className="container cta-band reveal">
        <div>
          <h2>See it on a real repo</h2>
          <p>
            The playground has six sample repos, from a FastAPI service to a pnpm monorepo. Edit their files and
            watch the generated YAML change.
          </p>
        </div>
        <div className="hero-actions">
          <a className="btn btn-primary" href={links.playground}>
            Open the playground
          </a>
          <a className="btn" href={links.docs('getting-started')}>
            Getting started
          </a>
        </div>
      </div>
    </section>
  </>
);
