import type { Page } from '@playwright/test'
import type { AnalysisRead, SystemHealth } from '../../src/api/types.gen'
import {
  GUEST_NOT_READY_SYSTEM,
  GUEST_READY_SYSTEM,
  MIXED_ANALYSES,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
  makeCleanAnalysis,
  makeDetectedAnalysis,
  mockAnalyses,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
  type AnalysesMockOptions,
} from './fixtures'

test.use({ timezoneId: 'UTC' })

async function openDashboard(
  page: Page,
  analyses: AnalysesMockOptions,
  health: SystemHealth = GUEST_READY_SYSTEM,
): Promise<void> {
  await mockShell(page, health)
  await mockAnalyses(page, analyses)
  await page.goto('/')
}

async function expectGuestReady(page: Page): Promise<void> {
  await expect(page.getByRole('button', { name: '+ SUBMIT', exact: true })).toBeEnabled()
}

const LONG_FILENAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(60)}.pdf.exe`

function manyAnalyses(count: number): AnalysisRead[] {
  return Array.from({ length: count }, (_, index) => {
    const id = count - index
    if (id === 12) return makeDetectedAnalysis({ id, filename: LONG_FILENAME })
    return id % 3 === 0 ? makeCleanAnalysis({ id }) : makeDetectedAnalysis({ id, score: id % 10, max_severity: 'high' })
  })
}

test('dashboard-populated', async ({ page }) => {
  await openDashboard(page, { items: MIXED_ANALYSES })
  await expect(page.locator('.analysis-row')).toHaveCount(MIXED_ANALYSES.length)
  await expectGuestReady(page)
  await page.screenshot({ path: screenshotPath('dashboard-populated') })
})

test('dashboard-empty', async ({ page }) => {
  await openDashboard(page, { items: [] })
  await expectGuestReady(page)
  await expect(page.getByText('no analyses yet')).toBeVisible()
  await page.screenshot({ path: screenshotPath('dashboard-empty') })
})

test('dashboard-empty-guest-not-ready', async ({ page }) => {
  await openDashboard(page, { items: [] }, GUEST_NOT_READY_SYSTEM)
  await expect(page.getByText('guest VM not ready')).toBeVisible()
  await expect(page.locator('.empty-reason')).toHaveText(GUEST_NOT_READY_SYSTEM.guest.message!)
  await page.screenshot({ path: screenshotPath('dashboard-empty-guest-not-ready') })
})

test('dashboard-filtered-no-match', async ({ page }) => {
  await openDashboard(page, { items: MIXED_ANALYSES })
  await expect(page.locator('.analysis-row')).toHaveCount(MIXED_ANALYSES.length)
  await page.getByLabel('Search analyses').fill('no-such-sample')
  await expect(page.getByText('no analyses match')).toBeVisible()
  await expect(page.getByRole('button', { name: '[CLEAR FILTERS]' })).toBeVisible()
  await page.screenshot({ path: screenshotPath('dashboard-filtered-no-match') })
})

test('dashboard-filtered-by-status', async ({ page }) => {
  await openDashboard(page, { items: MIXED_ANALYSES })
  await expect(page.locator('.analysis-row')).toHaveCount(MIXED_ANALYSES.length)
  await page.locator('.status-select').click()
  await page.getByRole('option', { name: 'FAILED', exact: true }).click()
  await expect(page.locator('.analysis-row')).toHaveCount(1)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('dashboard-filtered-by-status') })
})

test('dashboard-loading', async ({ page }) => {
  await openDashboard(page, { items: MIXED_ANALYSES, listDelayMs: 3000 })
  await expect(page.locator('.loader')).toBeVisible()
  await page.screenshot({ path: screenshotPath('dashboard-loading') })
})

test('dashboard-load-error', async ({ page }) => {
  await openDashboard(page, {
    items: [],
    listError: { status: 500, body: errorEnvelope('internal_error', 'database connection lost') },
  })
  await expect(page.getByText('failed to load: database connection lost')).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await page.screenshot({ path: screenshotPath('dashboard-load-error') })
})

test('dashboard-long-list', async ({ page }) => {
  const items = manyAnalyses(40)
  await openDashboard(page, { items, total: 143 })
  await expect(page.locator('.analysis-row')).toHaveCount(items.length)
  await expect(page.getByText('showing 40 of 143')).toBeVisible()
  await page.screenshot({ path: screenshotPath('dashboard-long-list'), fullPage: true })
})

test('dashboard-long-filename', async ({ page }) => {
  await openDashboard(page, {
    items: [makeDetectedAnalysis({ id: 2, filename: LONG_FILENAME }), makeCleanAnalysis({ id: 1 })],
  })
  await expect(page.locator('.analysis-row')).toHaveCount(2)
  await page.screenshot({ path: screenshotPath('dashboard-long-filename') })
})

test('a long list scrolls under a header and nav that stay docked', async ({ page }) => {
  const items = manyAnalyses(40)
  await openDashboard(page, { items, total: 143 })
  await expect(page.locator('.analysis-row')).toHaveCount(items.length)
  await page.mouse.wheel(0, 5000)
  await expect(page.getByText('showing 40 of 143')).toBeInViewport()
  const [header, drawer] = await Promise.all([page.locator('.q-header').boundingBox(), page.locator('.q-drawer').boundingBox()])
  expect(header!.y).toBe(0)
  expect(drawer!.y).toBeLessThanOrEqual(header!.height)
  expect(drawer!.y + drawer!.height).toBeGreaterThanOrEqual(page.viewportSize()!.height)
})

test('dashboard-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 800 })
  await openDashboard(page, { items: [...MIXED_ANALYSES, makeAnalysis({ id: 10, filename: LONG_FILENAME })] })
  await expect(page.locator('.analysis-row')).toHaveCount(MIXED_ANALYSES.length + 1)
  await page.screenshot({ path: screenshotPath('dashboard-narrow-600') })
})

test('row actions are reachable without scrolling the table at 600px', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 800 })
  await openDashboard(page, { items: MIXED_ANALYSES })
  await expect(page.locator('.analysis-row')).toHaveCount(MIXED_ANALYSES.length)
  const hiddenBeyondTable = await page.locator('.analyses-table-scroll').evaluate((wrapper) => wrapper.scrollWidth - wrapper.clientWidth)
  expect(hiddenBeyondTable).toBeLessThanOrEqual(0)
})

test('dashboard-delete-confirmation', async ({ page }) => {
  await openDashboard(page, { items: MIXED_ANALYSES })
  await expect(page.locator('.analysis-row')).toHaveCount(MIXED_ANALYSES.length)
  await page.getByRole('button', { name: 'Delete analysis 6' }).click()
  await expect(page.getByRole('dialog')).toContainText('Delete invoice_scan.exe?')
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('dashboard-delete-confirmation') })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`dashboard does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openDashboard(page, { items: [...MIXED_ANALYSES, makeAnalysis({ id: 10, filename: LONG_FILENAME })] })
    await expect(page.locator('.analysis-row')).toHaveCount(MIXED_ANALYSES.length + 1)
    await expectNoHorizontalOverflow(page)
  })
}
