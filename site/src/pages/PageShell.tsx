import { StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Footer } from '../components/Footer';
import { Header } from '../components/Header';
import type { PageId } from '../lib/links';
import '../styles/main.css';

export function mountPage(current: PageId, content: ReactNode) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Header current={current} />
      <main>{content}</main>
      <Footer />
    </StrictMode>
  );
}
