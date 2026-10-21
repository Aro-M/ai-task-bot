import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e-live',
  workers: 1,
  timeout: 90000,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report-live', open: 'never' }],
  ],
  outputDir: 'test-results-live',
  use: {
    baseURL: process.env.TASKBOT_QA_URL || 'http://localhost:18080',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
