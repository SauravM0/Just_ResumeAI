import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/tests/setup.ts'],
    css: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: [
        'src/lib/resumeText.ts',
        'src/lib/errorMessages.ts',
        'src/lib/api.ts',
        'src/store/generationStore.ts',
        'src/hooks/useGeneration.ts',
        'src/components/ui/BulletQualityBadge.tsx',
        'src/components/ui/RecruiterScoreCard.tsx',
        'src/components/ui/ScoreHistoryChart.tsx',
      ],
      thresholds: {
        statements: 50,
        branches: 40,
        functions: 50,
        lines: 50,
      },
    },
  },
})
