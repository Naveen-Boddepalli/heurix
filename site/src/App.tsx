import { CliExamples } from './components/CliExamples';
import { ComparisonTable } from './components/ComparisonTable';
import { DocsSection } from './components/DocsSection';
import { Footer } from './components/Footer';
import { Header } from './components/Header';
import { Hero } from './components/Hero';
import { HeuristicsGrid } from './components/HeuristicsGrid';
import { Playground } from './components/Playground';
import { VisibilitySection } from './components/VisibilitySection';

export function App() {
  return (
    <>
      <Header />
      <main>
        <Hero />
        <Playground />
        <ComparisonTable />
        <HeuristicsGrid />
        <CliExamples />
        <DocsSection />
        <VisibilitySection />
      </main>
      <Footer />
    </>
  );
}
