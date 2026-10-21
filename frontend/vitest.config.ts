import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      include: [
        'src/api.ts',
        'src/App.tsx',
        'src/TaskDialog.tsx',
        'src/dateTime.ts',
      ],
      thresholds: { lines: 80, statements: 80, functions: 75, branches: 70 },
    },
  },
});
