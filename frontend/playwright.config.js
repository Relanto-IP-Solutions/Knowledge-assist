import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

/** Config file lives in frontend/ — pin all outputs under frontend/ regardless of shell cwd */
const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  testDir: path.join(__dirname, 'e2e'),
  outputDir: path.join(__dirname, 'test-results'),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [['html', { outputFolder: path.join(__dirname, 'playwright-report'), open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev -- --port 4173 --host 127.0.0.1',
    cwd: __dirname,
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})

