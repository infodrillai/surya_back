import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'fs';
import path from 'path';

const getAppDir = () => {
  const rootApp = path.resolve(__dirname, '../backend/apps/clssurya/clssurya');
  if (fs.existsSync(rootApp)) return rootApp;
  const localApp = path.resolve(__dirname, '../clssurya');
  if (fs.existsSync(localApp)) return localApp;
  return rootApp;
};

function syncToFrappeWww() {
  return {
    name: 'sync-to-frappe-www',
    closeBundle() {
      const appDir = getAppDir();
      const src = path.join(appDir, 'public/surya/index.html');
      const wwwDir = path.join(appDir, 'www');
      const dest = path.join(wwwDir, 'surya.html');
      if (fs.existsSync(src)) {
        fs.mkdirSync(wwwDir, { recursive: true });
        fs.copyFileSync(src, dest);
        console.log(`[vite] Synced index.html to ${dest}`);
      }
    },
  };
}

export default defineConfig({
  base: '/assets/clssurya/surya/',
  plugins: [react(), syncToFrappeWww()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        headers: { 'X-Frappe-Site-Name': 'surya.local' },
      },
      '/socket.io': {
        target: 'http://127.0.0.1:9000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: path.resolve(getAppDir(), 'public/surya'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  test: { environment: 'node' },
});