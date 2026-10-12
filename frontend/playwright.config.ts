import { defineConfig, devices } from '@playwright/test'

// A distinct port from the Quasar dev server's default (5173, see quasar.config.ts) so this
// harness's own dev server instance never collides with the Docker dev stack's, should both
// ever run on the same host at once. quasar.config.ts reads DEV_SERVER_PORT for exactly this.
const PORT = 5190
const BASE_URL = `http://127.0.0.1:${PORT}`

export default defineConfig({
  testDir: './tests/screenshots',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { DEV_SERVER_PORT: String(PORT) },
  },
})
