import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
 
const __dirname = path.dirname(fileURLToPath(import.meta.url))
 
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const apiTarget = String(env.VITE_API_BASE || 'http://localhost:8000').replace(/\/$/, '')
 
  return {
    plugins: [react()],
    /** Always load `.env` from this folder (where `vite.config.js` lives), not the shell cwd. */
    envDir: __dirname,
    server: {
      port: parseInt(process.env.PORT || '5173'),
      /**
       * Lets Firebase `signInWithPopup` (Google / Microsoft) poll `window.closed` without
       * "Cross-Origin-Opener-Policy policy would block the window.closed call" in the console.
       */
      headers: {
        'Cross-Origin-Opener-Policy': 'same-origin-allow-popups',
      },
      /**
       * Proxy backend calls through Vite to avoid CORS and 404s.
       */
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true, secure: false },
        '/auth': { target: apiTarget, changeOrigin: true, secure: false },
        '/gmail': { target: apiTarget, changeOrigin: true, secure: false },
        '/integrations': { target: apiTarget, changeOrigin: true, secure: false },
        '/opportunities': { target: apiTarget, changeOrigin: true, secure: false },
        // Connector endpoints — must be proxied at their exact root-level paths.
        // Do NOT add a /drive/ prefix here; backend routes are /metrics/drive/...
        // and /authorize-info/drive/... (not /drive/metrics/...).
        '/metrics': { target: apiTarget, changeOrigin: true, secure: false },
        '/authorize-info': { target: apiTarget, changeOrigin: true, secure: false },
        '/authorize': { target: apiTarget, changeOrigin: true, secure: false },
        '/drive': { target: apiTarget, changeOrigin: true, secure: false },
        /** POST /zoom/discover (see integrationsAuthApi.discoverZoom) — root path, not under /integrations */
        '/zoom': { target: apiTarget, changeOrigin: true, secure: false },
        '/teams': { target: apiTarget, changeOrigin: true, secure: false },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setupTests.js',
      css: true,
      include: ['src/**/*.{test,spec}.{js,jsx}'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html'],
        /** Always write under frontend/ (this file’s directory), not repo cwd */
        reportsDirectory: path.join(__dirname, 'coverage'),
      },
    },
  }
})