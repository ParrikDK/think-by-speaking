import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8004', // v9 backend (audit M2: was proxying to the v8C on :8000)
    },
  },
  build: {
    outDir: '../backend/app/static',
    emptyOutDir: true,
    minify: false, // esbuild minification causes TDZ errors with this React bundle
  },
});
