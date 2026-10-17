import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser talks only to the Vite dev server; /api is forwarded to FastAPI.
// Same origin means the session cookie works without any CORS setup.
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
      '/healthz': { target: apiTarget, changeOrigin: false },
    },
  },
})
