import { defineConfig, devices } from '@playwright/test'

// Runs against the real stack, so there is no webServer and nothing is mocked. scripts/e2e.sh
// passes the frontend's published address and a sample file; see tests/e2e/submit-flow.spec.ts.
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8080'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  // An analysis takes about 75 s of guest time; the rest is headroom for a slow machine.
  timeout: 360_000,
  reporter: [['list']],
  use: { baseURL: BASE_URL },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
