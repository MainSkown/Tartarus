import type { Page } from '@playwright/test'
import type { SettingsBody } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  MIXED_ANALYSES,
  expect,
  expectNoHorizontalOverflow,
  mockAnalyses,
  mockSettings,
  mockShell,
  screenshotPath,
  test,
  validationErrorEnvelope,
  waitForFieldMessages,
  waitForTransitions,
  type AnalysesMockOptions,
} from './fixtures'
import { mockGuests } from './guest-data'
import { FLAT_HOME, LONG_PRESET, PRESETS_DOWN, SMALL_OFFICE, THREE_PRESETS, mockLanPresets } from './submit-lan-data'

test.use({ timezoneId: 'UTC' })

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1400 })
  await mockGuests(page)
})

const STORED_SETTINGS: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 240,
  default_interactive: false,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

const SAMPLE = { name: 'invoice_scan.exe', mimeType: 'application/octet-stream', buffer: Buffer.alloc(48 * 1024, 7) }

async function openSubmitDialog(page: Page, analyses: Partial<AnalysesMockOptions> = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: STORED_SETTINGS })
  await mockAnalyses(page, { items: MIXED_ANALYSES, ...analyses })
  await page.goto('/')
  await page.getByRole('button', { name: '+ SUBMIT', exact: true }).click()
  await expect(page.getByLabel('TIMEOUT')).toHaveValue('240')
  await waitForTransitions(page)
  await page.locator('input[type="file"]').setInputFiles(SAMPLE)
  await expect(page.locator('.file-hash')).toHaveText(/sha256 [0-9a-f]{64}/)
}

const lanSwitch = (page: Page) => page.getByRole('switch', { name: 'SIMULATE LOCAL NETWORK' })

async function switchLanOn(page: Page): Promise<void> {
  await lanSwitch(page).click()
  await expect(lanSwitch(page)).toBeChecked()
}

async function shoot(page: Page, name: string): Promise<void> {
  // The pointer is left wherever the last click was, which a layout change can put over a row or the drop zone.
  await page.mouse.move(0, 0)
  await expectNoHorizontalOverflow(page)
  await waitForFieldMessages(page)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name) })
}

test('submit-lan-off', async ({ page }) => {
  await openSubmitDialog(page)
  await expect(lanSwitch(page)).not.toBeChecked()
  await expect(page.locator('.lan-note')).toHaveText('The guest sees the gateway and nothing else on its network.')
  await expect(page.locator('.preset-list')).toHaveCount(0)
  await shoot(page, 'submit-lan-off')
})

test('submit-lan-picker-none-chosen', async ({ page }) => {
  await mockLanPresets(page, { body: THREE_PRESETS })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await expect(page.locator('.preset-row')).toHaveCount(3)
  await expect(page.locator('.submit-reason')).toHaveText('Choose a local network preset')
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
  await shoot(page, 'submit-lan-picker-none-chosen')
})

test('submit-lan-preset-chosen', async ({ page }) => {
  await mockLanPresets(page, { body: THREE_PRESETS })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await page.getByRole('radio', { name: /Small office/ }).check()
  await expect(page.locator('.preset-row--selected .preset-hosts')).toHaveText(
    '6 hosts: domain-controller, file-server, workstation ×2, sql-server, printer',
  )
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeEnabled()
  await shoot(page, 'submit-lan-preset-chosen')
})

test('submit-lan-only-preset', async ({ page }) => {
  await mockLanPresets(page, { body: [FLAT_HOME] })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await expect(page.getByRole('radio', { name: /Flat home LAN/ })).toBeChecked()
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeEnabled()
  await shoot(page, 'submit-lan-only-preset')
})

test('submit-lan-loading', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await mockLanPresets(page, { body: THREE_PRESETS, gate })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await expect(page.locator('.lan-fields .loader')).toBeVisible()
  await expect(page.locator('.submit-reason')).toHaveText('Reading the local network presets…')
  await shoot(page, 'submit-lan-loading')
  release()
})

test('submit-lan-load-error', async ({ page }) => {
  await mockLanPresets(page, { status: 502, body: PRESETS_DOWN })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await expect(page.locator('.lan-fields')).toContainText('failed to load: The guest control service is not reachable')
  await expect(page.locator('.submit-reason')).toHaveText('The local network presets could not be loaded')
  await shoot(page, 'submit-lan-load-error')
})

test('submit-lan-no-presets', async ({ page }) => {
  await mockLanPresets(page, { body: [] })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await expect(page.locator('.lan-fields')).toContainText('> no local network presets')
  await expect(page.locator('.submit-reason')).toHaveText('No local network preset is available')
  await shoot(page, 'submit-lan-no-presets')
})

test('submit-lan-route-internet', async ({ page }) => {
  await mockLanPresets(page, { body: THREE_PRESETS })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await page.getByRole('radio', { name: /Small office/ }).check()
  await page.getByText('internet', { exact: true }).click()
  await expect(lanSwitch(page)).not.toBeChecked()
  await expect(lanSwitch(page)).toBeDisabled()
  await expect(page.locator('.lan-note')).toHaveText(
    'Not available with the internet route: pick another route to simulate a local network.',
  )
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeEnabled()
  await shoot(page, 'submit-lan-route-internet')
})

test('submit-lan-backend-refusal', async ({ page }) => {
  await mockLanPresets(page, { body: THREE_PRESETS })
  await openSubmitDialog(page, {
    createResponse: {
      status: 422,
      body: validationErrorEnvelope([{ field: 'lan_preset', message: 'Unknown local network preset' }]),
    },
  })
  await switchLanOn(page)
  await page.getByRole('radio', { name: /Flat home LAN/ }).check()
  await page.getByRole('button', { name: '▶ DETONATE' }).click()
  await expect(page.locator('.preset-error')).toHaveText('Unknown local network preset')
  await shoot(page, 'submit-lan-backend-refusal')
})

test('submit-lan-long-preset', async ({ page }) => {
  await mockLanPresets(page, { body: [LONG_PRESET, SMALL_OFFICE] })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await page.getByRole('radio', { name: /Regional headquarters/ }).check()
  await shoot(page, 'submit-lan-long-preset')
})

test('submit-lan-narrow-360', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 1800 })
  await mockLanPresets(page, { body: [...THREE_PRESETS, LONG_PRESET] })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await page.getByRole('radio', { name: /Small office/ }).check()
  await page.locator('.preset-list').evaluate((list) => list.scrollTo({ top: 0 }))
  await shoot(page, 'submit-lan-narrow-360')
})

test('submit-lan-narrow-360-long-preset', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 1800 })
  await mockLanPresets(page, { body: [LONG_PRESET, FLAT_HOME] })
  await openSubmitDialog(page)
  await switchLanOn(page)
  await page.getByRole('radio', { name: /Regional headquarters/ }).check()
  await page.locator('.preset-list').evaluate((list) => list.scrollTo({ top: 0 }))
  await shoot(page, 'submit-lan-narrow-360-long-preset')
})

test('submit-lan-narrow-360-off', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 1400 })
  await openSubmitDialog(page)
  await shoot(page, 'submit-lan-narrow-360-off')
})

test('submit-lan-focus-switch', async ({ page }) => {
  await mockLanPresets(page, { body: THREE_PRESETS })
  await openSubmitDialog(page)
  await page.locator('#route-drop').focus()
  await page.keyboard.press('Tab')
  await expect(lanSwitch(page)).toBeFocused()
  await shoot(page, 'submit-lan-focus-switch')
})

test('submit-lan-focus-picker', async ({ page }) => {
  await mockLanPresets(page, { body: THREE_PRESETS })
  await openSubmitDialog(page)
  await page.locator('#route-drop').focus()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Space')
  await expect(lanSwitch(page)).toBeChecked()
  await expect(page.locator('.preset-row')).toHaveCount(3)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('radio', { name: /Small office/ })).toBeFocused()
  await shoot(page, 'submit-lan-focus-picker')
})
