import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Focused unit tests only: parsers, formatters and server-side rendering of
// the Markdown answer. No browser or DOM emulation is needed or installed.
export default defineConfig({
  plugins: [react()],
  test: { environment: 'node', include: ['src/**/*.test.{ts,tsx}'] },
})
