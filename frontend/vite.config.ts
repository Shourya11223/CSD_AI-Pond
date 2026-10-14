import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite dev server config:
//   /api/* requests are proxied to the FastAPI backend running on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
