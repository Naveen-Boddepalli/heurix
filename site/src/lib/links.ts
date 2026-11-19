/** Base-aware links between the site's pages (BASE_URL is "/" locally, "/heurix/" on Pages). */
const BASE = import.meta.env.BASE_URL;

export type PageId = 'home' | 'playground' | 'docs';

export const links = {
  home: BASE,
  playground: `${BASE}playground/`,
  docs: (docId?: string) => `${BASE}docs/${docId ? `#${docId}` : ''}`,
  asset: (path: string) => `${BASE}${path}`,
};
