// Synced docs (see scripts/sync-llms.mjs). Kept separate so only the docs page loads them.
import generatedDocs from './generatedDocs.json';

export interface DocEntry {
  id: string;
  title: string;
  file: string;
  group: string;
  markdown: string;
}

export const SITE_DOCS: {
  llmsTxt: string;
  llmsFullBytes: number;
  llmsFullLines: number;
  docs: DocEntry[];
} = generatedDocs;
