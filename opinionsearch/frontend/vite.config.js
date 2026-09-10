import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const frontendRoot = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => {
  const { OPINIONSEARCH_API_TARGET: apiTarget } = loadEnv(mode, frontendRoot, 'OPINIONSEARCH_')
  return {
    root: frontendRoot,
    plugins: [react()],
    server: {
      port: 5174,
      strictPort: true,
      // Only connect to a backend explicitly selected for this project.
      // Keep the browser's localhost Host header when Docker resolves "web".
      proxy: apiTarget && mode !== 'demo'
        ? { '/api': { target: apiTarget, changeOrigin: false } }
        : undefined,
    },
    preview: { port: 4174, strictPort: true },
  }
})
