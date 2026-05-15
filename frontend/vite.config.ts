import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// Backend URL: configurable so the same vite.config works on the host
// (default http://localhost:8000) and inside the docker dev container
// (VITE_BACKEND_URL=http://backend:8000 — set in Dockerfile.frontend.dev).
const backendUrl = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000';
const backendWsUrl = backendUrl.replace(/^http/, 'ws');

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirror tsconfig.json `paths` so build-time imports work the same as
    // editor + vitest. Without this, `import x from "@/lib/api"` resolves
    // in dev/tests but fails at `vite build` time.
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // host:true binds 0.0.0.0 so the dev server is reachable from
    // outside the container. Harmless for host-mode dev.
    host: true,
    strictPort: true,
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/ws': {
        target: backendWsUrl,
        ws: true,
      },
    },
  },
});
