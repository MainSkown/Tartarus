import type { Page } from '@playwright/test'
import type { Guest, SettingsBody } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  MIXED_ANALYSES,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  mockAnalyses,
  mockSettings,
  mockShell,
  screenshotPath,
  test,
  waitForFieldMessages,
  waitForTransitions,
  type AnalysesMockOptions,
} from './fixtures'
import { GUEST_BUILDING, GUEST_DEFENDER_OFF, GUEST_DEFENDER_ON, mockGuests } from './guest-data'

test.use({ timezoneId: 'UTC' })

const STORED_SETTINGS: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 240,
  default_interactive: true,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

const GUEST_4_GB: Guest = { ...GUEST_DEFENDER_ON, resources: { vcpus: 2, ram_mb: 4096, disk_gb: 60 } }
const GUEST_16_GB: Guest = { ...GUEST_DEFENDER_OFF, resources: { vcpus: 4, ram_mb: 16384, disk_gb: 80 } }

const SAMPLE = { name: 'invoice_scan.exe', mimeType: 'application/octet-stream', buffer: Buffer.alloc(48 * 1024, 7) }
const LONG_NAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(120)}.pdf.exe`
const DISK_REFUSAL = 'A memory dump needs 20.3 GB free on the CAPE volume; 12.0 GB are free.'

test.beforeEach(async ({ page }) => {
  await mockGuests(page, { guests: [GUEST_4_GB, GUEST_16_GB] })
})

async function openSubmitDialog(page: Page, analyses: Partial<AnalysesMockOptions> = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockSettings(page, { getBody: STORED_SETTINGS })
  await mockAnalyses(page, { items: MIXED_ANALYSES, ...analyses })
  await page.goto('/')
  await page.getByRole('button', { name: '+ SUBMIT', exact: true }).click()
  await expect(page.getByLabel('TIMEOUT')).toHaveValue('240')
  await waitForTransitions(page)
}

function memorySwitch(page: Page) {
  return page.getByRole('switch', { name: 'FULL MEMORY DUMP + VOLATILITY' })
}

function keepSwitch(page: Page) {
  return page.getByRole('switch', { name: 'KEEP THE DUMP AFTER THE FINDINGS ARE EXTRACTED' })
}

async function chooseFile(page: Page, file: { name: string; mimeType: string; buffer: Buffer } = SAMPLE): Promise<void> {
  await page.locator('input[type="file"]').setInputFiles(file)
  await expect(page.locator('.file-hash')).toHaveText(/sha256 [0-9a-f]{64}/)
}

async function switchMemoryOn(page: Page): Promise<void> {
  await memorySwitch(page).click()
  await expect(memorySwitch(page)).toBeChecked()
  await expect(page.locator('.memory-note')).toBeVisible()
}

test('submit-memory-default', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await expect(memorySwitch(page)).not.toBeChecked()
  await expect(page.locator('.memory-note')).toHaveCount(0)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-memory-default') })
})

test('submit-memory-on-warning', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await switchMemoryOn(page)
  await expect(page.locator('.memory-note')).toHaveText('Adds about 4.3 GB of disk and a few seconds of processing.')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-memory-on-warning') })
})

test('submit-memory-keep-ticked', async ({ page }) => {
  await openSubmitDialog(page)
  await chooseFile(page)
  await switchMemoryOn(page)
  await keepSwitch(page).click()
  await expect(keepSwitch(page)).toBeChecked()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-memory-keep-ticked') })
})

test('submit-memory-16-gb-guest', async ({ page }) => {
  await mockGuests(page, { guests: [GUEST_16_GB] })
  await openSubmitDialog(page)
  await chooseFile(page)
  await switchMemoryOn(page)
  await expect(page.locator('.memory-note')).toHaveText('Adds about 16.3 GB of disk and a few seconds of processing.')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-memory-16-gb-guest') })
})

test('submit-memory-disk-refusal', async ({ page }) => {
  await openSubmitDialog(page, {
    createResponse: { status: 409, body: errorEnvelope('conflict', DISK_REFUSAL) },
  })
  await chooseFile(page)
  await switchMemoryOn(page)
  await page.getByRole('button', { name: '▶ DETONATE' }).click()
  await expect(page.locator('.memory-error')).toHaveText(DISK_REFUSAL)
  await expect(page.locator('.error-banner')).toHaveCount(0)
  await waitForFieldMessages(page)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-memory-disk-refusal') })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`submit-memory-keep-at-${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openSubmitDialog(page)
    await chooseFile(page, { ...SAMPLE, name: LONG_NAME })
    await switchMemoryOn(page)
    await keepSwitch(page).click()
    await expect(keepSwitch(page)).toBeChecked()
    await waitForTransitions(page)
    await expectNoHorizontalOverflow(page)
    const box = await page.locator('.submit-dialog').boundingBox()
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await page.screenshot({ path: screenshotPath(`submit-memory-keep-at-${width}px`) })
  })
}

test('submit-memory-no-guest-ready', async ({ page }) => {
  await mockGuests(page, { guests: [GUEST_BUILDING] })
  await openSubmitDialog(page)
  await chooseFile(page)
  await switchMemoryOn(page)
  await expect(page.locator('.submit-reason')).toContainText('No guest is ready')
  await expect(page.getByRole('button', { name: '▶ DETONATE' })).toBeDisabled()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('submit-memory-no-guest-ready') })
})
