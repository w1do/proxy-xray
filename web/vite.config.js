import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const KIT = process.env.KIT_DEV_API || 'http://127.0.0.1:4050';
const forwardAsKit = {
  target: KIT,
  changeOrigin: true,
  configure: (proxy) => proxy.on('proxyReq', (req) => req.setHeader('origin', KIT)),
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/',
  build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false, modulePreload: { polyfill: false } },
  server: { host: '127.0.0.1', port: 5173, strictPort: true,
            proxy: { '/api': forwardAsKit, '/login': forwardAsKit } },
});
