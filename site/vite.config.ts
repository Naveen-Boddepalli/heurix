import { fileURLToPath } from 'node:url';
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
    // One HTML file per page, so GitHub Pages serves /playground/ and /docs/ directly.
    rollupOptions: {
      input: {
        home: fileURLToPath(new URL('./index.html', import.meta.url)),
        playground: fileURLToPath(new URL('./playground/index.html', import.meta.url)),
        docs: fileURLToPath(new URL('./docs/index.html', import.meta.url)),
      },
    },
  },
});
