import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend URL: configurable so the same vite.config works on the host
// (default http://localhost:8000) and inside the docker dev container
// (VITE_BACKEND_URL=http://backend:8000 — set in Dockerfile.frontend.dev).
const backendUrl = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000';
const backendWsUrl = backendUrl.replace(/^http/, 'ws');

export default defineConfig({
  plugins: [react()],
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
