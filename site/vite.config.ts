import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Use /heurix/ when built for GitHub Pages (SITE_BASE=/heurix/), or / for local dev/preview.
const base = process.env.SITE_BASE ?? '/';

export default defineConfig({
  base,
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
