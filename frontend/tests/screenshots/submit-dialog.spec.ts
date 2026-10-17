import type { Page } from '@playwright/test'
import type { SettingsBody } from '../../src/api/types.gen'
import {
  GUEST_NOT_READY_SYSTEM,
  GUEST_READY_SYSTEM,
  MIXED_ANALYSES,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
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

test.use({ timezoneId: 'UTC' })

test.beforeEach(async ({ page }) => {
  await mockGuests(page)
})

// Not the backend defaults (interactive is on, the backend's is off), so waiting for this timeout
// and switch proves the dialog applied the stored settings.
const STORED_SETTINGS: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 240,
  default_interactive: true,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

const SAMPLE = { name: 'invoice_scan.exe', mimeType: 'application/octet-stream', buffer: Buffer.alloc(48 * 1024, 7) }
const LONG_NAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(120)}.pdf.exe`

async function openSubmitDialog(page: Page, analyses: Partial<AnalysesMockOptions> = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: STORED_SETTINGS })
  await mockAnalyses(page, { items: MIXED_ANALYSES, ...analyses })
  await page.goto('/')
  await page.getByRole('button', { name: '+ SUBMIT', exact: true }).click()
  await expect(page.getByLabel('TIMEOUT')).toHaveValue('240')
  await expect(interactiveSwitch(page)).toBeChecked()
  await waitForTransitions(page)
}

function interactiveSwitch(page: Page) {
  return page.getByRole('switch', { name: 'INTERACTIVE DESKTOP' })
}

async function chooseFile(page: Page, file: { name: string; mimeType: string; buffer: Buffer } = SAMPLE): Promise<void> {
  await page.locator('input[type="file"]').setInputFiles(file)
  await expect(page.locator('.file-hash')).toHaveText(/sha256 [0-9a-f]{64}/)
}

test('submit-dialog-default', async ({ page }) => {
  await openSubmitDialog(page)
  await expect(page.locator('.submit-reason')).toHaveText('Choose a sample to analyse')
  await expect(page.locator('.interactive-note')).toContainText('The run lasts the full timeout (4 min) unless you press END RUN on the live page.')
  await page.screenshot({ path: screenshotPath('submit-dialog-default') })
})

test('submit-dialog-drag-over', async ({ page }) => {
  await openSubmitDialog(page)
  await page.locator('.drop-zone').dispatchEvent('dragover')
  await expect(page.locator('.drop-zone--over')).toBeVisible()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-drag-over') })
})

test('submit-dialog-file-chosen', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await expect(page.locator('.file-name')).toHaveText('invoice_scan.exe')
  await expect(page.locator('.file-size')).toBeVisible()
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeEnabled()
  await page.screenshot({ path: screenshotPath('submit-dialog-file-chosen') })
})

test('submit-dialog-long-filename', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page, { ...SAMPLE, name: LONG_NAME })
  await page.screenshot({ path: screenshotPath('submit-dialog-long-filename') })
})

test('submit-dialog-internet-route', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await page.getByText('internet', { exact: true }).click()
  await expect(page.locator('.internet-warning')).toBeVisible()
  await expect(page.locator('input[value="internet"]')).toBeChecked()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-internet-route') })
})

test('submit-dialog-interactive-off', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await interactiveSwitch(page).click()
  await expect(interactiveSwitch(page)).not.toBeChecked()
  await expect(page.locator('.interactive-note')).toContainText('The run ends once the sample has exited')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-interactive-off') })
})

test('submit-dialog-interactive-long-timeout', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await page.getByLabel('TIMEOUT').fill('1200')
  await expect(page.locator('.interactive-note')).toContainText('The run lasts the full timeout (20 min) unless you press END RUN on the live page.')
  await waitForFieldMessages(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-interactive-long-timeout') })
})

test('submit-dialog-invalid-timeout', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await page.getByLabel('TIMEOUT').fill('30')
  await expect(page.getByText('Whole seconds, 60 to 1200')).toBeVisible()
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
  await waitForFieldMessages(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-invalid-timeout') })
})

test('submit-dialog-submitting', async ({ page }) => {
  await openSubmitDialog(page, {
    createResponse: { status: 201, body: makeAnalysis({ id: 10, filename: SAMPLE.name }), delayMs: 5000 },
  })
  await chooseFile(page)
  await page.getByRole('button', { name: '▶ DETONATE' }).click()
  await expect(page.locator('.submit-btn .q-spinner')).toBeVisible()
  await expect(page.getByLabel('TIMEOUT')).toBeDisabled()
  await expect(interactiveSwitch(page)).toBeDisabled()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-submitting') })
})

test('submit-dialog-sends-the-switch', async ({ page }) => {
  await openSubmitDialog(page, { createResponse: { status: 201, body: makeAnalysis({ id: 10, filename: SAMPLE.name }) } })
  await chooseFile(page)
  await interactiveSwitch(page).click()
  const request = page.waitForRequest((candidate) => candidate.method() === 'POST' && candidate.url().includes('/analyses'))
  await page.getByRole('button', { name: '▶ DETONATE' }).click()
  const body = (await request).postDataBuffer()!.toString()
  expect(body).toContain('"interactive":false')
})

test('submit-dialog-field-errors', async ({ page }) => {
  await openSubmitDialog(page, {
    createResponse: {
      status: 422,
      body: validationErrorEnvelope([
        { field: 'file', message: 'File is empty' },
        { field: 'timeout', message: 'must not exceed the guest limit of 600 seconds' },
        { field: 'package', message: 'unknown package "exe64"' },
        { field: 'interactive', message: 'Input should be a valid boolean' },
      ]),
    },
  })
  await chooseFile(page)
  await page.getByRole('button', { name: '▶ DETONATE' }).click()
  const dialog = page.locator('.submit-dialog')
  await expect(dialog.getByText('File is empty')).toBeVisible()
  await expect(dialog.getByText('must not exceed the guest limit of 600 seconds')).toBeVisible()
  await expect(dialog.getByText('unknown package "exe64"')).toBeVisible()
  await expect(dialog.getByText('Input should be a valid boolean')).toBeVisible()
  await waitForFieldMessages(page)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-field-errors') })
})

test('submit-dialog-error-banner', async ({ page }) => {
  await openSubmitDialog(page, {
    createResponse: { status: 500, body: errorEnvelope('internal_error', 'CAPE rejected the task: sample storage is full') },
  })
  await chooseFile(page)
  await page.getByRole('button', { name: '▶ DETONATE' }).click()
  await expect(page.locator('.error-banner')).toHaveText('CAPE rejected the task: sample storage is full')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-error-banner') })
})

test('submit-dialog-guest-not-ready', async ({ page }) => {
  await mockShell(page, GUEST_NOT_READY_SYSTEM)
  await mockAnalyses(page, { items: MIXED_ANALYSES })
  await page.goto('/')
  const submit = page.getByRole('button', { name: '+ SUBMIT', exact: true })
  await expect(submit).toBeDisabled()
  await expect(page.getByRole('group', { name: GUEST_NOT_READY_SYSTEM.guest.message! })).toBeVisible()
  await page.locator('.submit-wrapper').hover()
  const tooltip = page.getByRole('tooltip')
  await expect(tooltip).toHaveText(GUEST_NOT_READY_SYSTEM.guest.message!)
  await expect(tooltip).toBeVisible()
  await expect(tooltip).toHaveCSS('opacity', '1')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-guest-not-ready') })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`submit dialog does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openSubmitDialog(page)
    await chooseFile(page, { ...SAMPLE, name: LONG_NAME })
    await expectNoHorizontalOverflow(page)
    await expect(page.locator('.submit-dialog')).toBeVisible()
    const box = await page.locator('.submit-dialog').boundingBox()
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
  })
}

test('submit-dialog-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 800 })
  await openSubmitDialog(page)
  await chooseFile(page, { ...SAMPLE, name: LONG_NAME })
  await page.getByText('internet', { exact: true }).click()
  await expect(page.locator('.internet-warning')).toBeVisible()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-dialog-narrow-600') })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`submit dialog does not jump when the interactive switch is flipped at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openSubmitDialog(page)
    await page.getByLabel('TIMEOUT').fill('1200')
    const dialogHeight = async () => (await page.locator('.submit-dialog').boundingBox())!.height
    await expect(page.locator('.interactive-note')).toContainText('unless you press END RUN on the live page.')
    const interactiveHeight = await dialogHeight()

    await interactiveSwitch(page).click()
    await expect(page.locator('.interactive-note')).toContainText('The run ends once the sample has exited')
    expect(await dialogHeight(), 'the dialog changed height with the switch').toBe(interactiveHeight)
  })
}
