import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The dev server only proxies /api to the real local FastAPI backend; there is
// no mock server. Set NEWTON_API_TARGET (shell or .env.local) when the backend
// listens elsewhere. Production builds are served by FastAPI itself.
// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // npm scripts run with web/ as the working directory, so '.' is this folder.
  const env = loadEnv(mode, '.', 'NEWTON_')
  const apiTarget = env.NEWTON_API_TARGET ?? 'http://127.0.0.1:18765'
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5273,
      strictPort: true,
      proxy: { '/api': { target: apiTarget, changeOrigin: false } },
    },
    preview: { host: '127.0.0.1', port: 5274, strictPort: true },
    build: { outDir: 'dist', sourcemap: true },
  }
})
