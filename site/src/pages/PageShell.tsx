import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BackgroundField } from '../components/BackgroundField';
import { Footer } from '../components/Footer';
import { Header } from '../components/Header';
import type { PageId } from '../lib/links';
import '../styles/main.css';
import '../styles/motion.css';

export function mountPage(current: PageId, content: ReactNode) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BackgroundField />
      <Header current={current} />
      <main>{content}</main>
      <Footer />
    </StrictMode>
  );
}
