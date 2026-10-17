import type { SettingsBody } from '../../src/api/types.gen'
import {
  expect,
  mockSettings,
  mockShell,
  screenshotPath,
  test,
  validationErrorEnvelope,
  waitForFieldMessages,
} from './fixtures'
import { mockGuests } from './guest-data'

// Deliberately not the backend's defaults, so the screenshot proves the page is rendering
// server-returned values rather than hardcoded fallbacks.
const STORED_SETTINGS: SettingsBody = {
  default_route: 'tor',
  default_timeout: 240,
  default_interactive: true,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

test.beforeEach(async ({ page }) => {
  await mockGuests(page)
})

test('settings-loaded', async ({ page }) => {
  await mockShell(page)
  await mockSettings(page, { getBody: STORED_SETTINGS })
  await page.goto('/settings')
  await expect(page.locator('.save-btn')).toBeVisible()
  await expect(page.getByLabel('DEFAULT TIMEOUT')).toHaveValue('240')
  await expect(page.locator('input[value="tor"]')).toBeChecked()
  await page.screenshot({ path: screenshotPath('settings-loaded') })
})

test('settings form has the same gap between every pair of components', async ({ page }) => {
  // jsdom has no layout, so this can only be checked in a real browser. Quasar reserves 20px
  // of padding under each q-input for an error message, inside the input's own box, so the
  // visible gaps alternated between 24px and 44px while the boxes themselves were evenly
  // spaced. Measure what is drawn: an input's bordered control, not its padded wrapper.
  await mockShell(page)
  await mockSettings(page, { getBody: STORED_SETTINGS })
  await page.goto('/settings')
  await expect(page.locator('.save-btn')).toBeVisible()
  const gaps = await page.locator('.settings-form > *').evaluateAll((elements) => {
    const boxes = elements.map((element) =>
      (element.querySelector('.q-field__control') ?? element).getBoundingClientRect(),
    )
    return boxes.slice(1).map((box, index) => Math.round(box.top - boxes[index]!.bottom))
  })
  expect(gaps).toHaveLength(6)
  expect(new Set(gaps).size, `gaps between components were ${gaps.join(', ')}px`).toBe(1)
})

test('settings-loading', async ({ page }) => {
  await mockShell(page)
  await mockSettings(page, { getBody: STORED_SETTINGS, getDelayMs: 3000 })
  await page.goto('/settings')
  await expect(page.locator('.loader')).toBeVisible()
  await page.screenshot({ path: screenshotPath('settings-loading') })
})

test('settings-validation-error', async ({ page }) => {
  await mockShell(page)
  await mockSettings(page, {
    getBody: STORED_SETTINGS,
    putResponse: {
      status: 422,
      body: validationErrorEnvelope([
        { field: 'default_route', message: 'Input should be a valid route' },
        { field: 'disk_warn_gb', message: 'must be greater than disk_block_gb' },
      ]),
    },
  })
  await page.goto('/settings')
  await expect(page.locator('.save-btn')).toBeVisible()
  await page.locator('.save-btn').click()
  // Scoped to the form: the real API error interceptor also raises a `tt-error` toast for any
  // non-2xx response (src/boot/api.ts), which repeats both messages in its caption — exactly
  // what the real running app does, and worth keeping in the screenshot, but it means the bare
  // text also matches inside that toast, so the inline-error assertions need to stay scoped to
  // the form to resolve to one element each.
  const form = page.locator('.settings-form')
  await expect(form.getByText('Input should be a valid route')).toBeVisible()
  await expect(form.getByText('must be greater than disk_block_gb')).toBeVisible()
  await waitForFieldMessages(page)
  await page.screenshot({ path: screenshotPath('settings-validation-error') })
})

test('settings-saved', async ({ page }) => {
  await mockShell(page)
  await mockSettings(page, { getBody: STORED_SETTINGS, putResponse: { status: 200, body: STORED_SETTINGS } })
  await page.goto('/settings')
  await expect(page.locator('.save-btn')).toBeVisible()
  await page.locator('.save-btn').click()
  await expect(page.locator('.tt-toast--success')).toBeVisible()
  await expect(page.locator('.tt-toast--success')).toContainText('Settings saved')
  await page.screenshot({ path: screenshotPath('settings-saved') })
})
