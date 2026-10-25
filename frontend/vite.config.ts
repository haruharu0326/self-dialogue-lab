import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The built screen is served by the Python API on the same local port.
const api = 'http://127.0.0.1:8501'

export default defineConfig({
  plugins: [react()],
  build: { outDir: '../src/self_dialogue_lab/static', emptyOutDir: true },
  server: { host: '127.0.0.1', proxy: { '/api': api } },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/setupTests.ts'] },
})
