import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/testSetup.ts',
    testTimeout: 15_000,
    fileParallelism: false,
    maxWorkers: 1,
  },
})
