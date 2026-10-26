import {
  expect,
  mockSettings,
  mockShell,
  mockVersionGet,
  RELEASE_VERSION,
  screenshotPath,
  test,
} from './fixtures'
import { mockGuests } from './guest-data'
import type { SettingsBody } from '../../src/api/types.gen'

const STORED_SETTINGS: SettingsBody = {
  default_route: 'drop',
  default_timeout: 240,
  default_interactive: true,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

const LONG_COMMIT = 'the-commit-of-a-build-made-from-a-long-feature-branch-name-0123456789abcdef'

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 })
  await mockGuests(page)
  await mockShell(page)
  await mockSettings(page, { getBody: STORED_SETTINGS })
})

test('about-card-loaded', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.locator('.about-version')).toHaveText(RELEASE_VERSION.version)
  await expect(page.locator('.about-commit')).toHaveText(RELEASE_VERSION.commit!)
  await expect(page.locator('.about-attribution')).toContainText('© 2026 The MITRE Corporation')
  await expect(page.locator('.about-attribution-link')).toBeVisible()
  await page.screenshot({ path: screenshotPath('about-card-loaded') })
})

test('about-card-loading', async ({ page }) => {
  await mockVersionGet(page, { delayMs: 3000 })
  await page.goto('/settings')
  await expect(page.locator('.about-card .loader')).toBeVisible()
  await page.screenshot({ path: screenshotPath('about-card-loading') })
})

test('about-card-failed', async ({ page }) => {
  await mockVersionGet(page, {
    status: 500,
    body: { error: { code: 'internal_error', message: 'Internal Server Error', details: {} } },
  })
  await page.goto('/settings')
  await expect(page.locator('.about-card')).toContainText('> failed to load version')
  await page.screenshot({ path: screenshotPath('about-card-failed') })
})

test('about-card-long-commit-narrow', async ({ page }) => {
  await mockVersionGet(page, { body: { ...RELEASE_VERSION, commit: LONG_COMMIT } })
  await page.setViewportSize({ width: 360, height: 1000 })
  await page.goto('/settings')
  await expect(page.locator('.about-commit')).toHaveText(LONG_COMMIT)
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflows, 'the About card must not scroll the page sideways').toBe(false)
  await expect(page.locator('.about-attribution')).toBeVisible()
  await page.screenshot({ path: screenshotPath('about-card-long-commit-narrow') })
})
