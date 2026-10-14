import type { Page } from '@playwright/test'
import { analysisAnnotations, tag, LONG_TAG } from './annotations-data'
import {
  ANALYSIS_ID,
  FINISHED_ANALYSIS,
  openAnalysis,
  openDashboard,
  snapshot,
} from './export-mock'
import {
  MIXED_ANALYSES,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
  test,
} from './fixtures'

const RUNNING_ANALYSIS = makeAnalysis({
  id: ANALYSIS_ID,
  status: 'processing',
  filename: 'payload.bin',
  started_at: '2026-10-12T09:14:30Z',
})
const LONG_FILENAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(60)}.pdf.exe`

async function openHeaderMenu(page: Page): Promise<void> {
  await page.getByRole('button', { name: '[EXPORT]' }).click()
  await expect(page.locator('.export-entries')).toBeVisible()
}

async function openRowMenu(page: Page, id: number): Promise<void> {
  await page.getByRole('button', { name: `Actions for analysis ${id}` }).click()
  await expect(page.locator('.row-menu')).toBeVisible()
}

// ---------- Analysis header ----------

test('export-header-menu-finished', async ({ page }) => {
  await openAnalysis(page)
  await openHeaderMenu(page)
  await expect(page.locator('.export-entries__hint')).toHaveCount(0)
  await snapshot(page, 'header-01-menu-finished')
})

test('export-header-menu-unfinished-reports-disabled', async ({ page }) => {
  await openAnalysis(page, RUNNING_ANALYSIS)
  await openHeaderMenu(page)
  await expect(page.locator('.export-entries__hint')).toHaveText('Reports are built from a finished analysis')
  await snapshot(page, 'header-02-menu-unfinished-reports-disabled')
})

const MANY_TAGS = [LONG_TAG, 'phishing', 'emotet', 'tlp:amber', 'dropper', 'needs-review', ...'abcdefghij'.split('')]

test('export-header-many-tags-keep-delete-pinned-top-right', async ({ page }) => {
  const annotations = analysisAnnotations({ tags: MANY_TAGS.map((name) => tag(name)) })
  await openAnalysis(page, { ...FINISHED_ANALYSIS, tags: MANY_TAGS }, { annotations })
  await expect(page.locator('.analysis-header .tag-chip').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  const title = (await page.locator('.analysis-header__title').boundingBox())!
  const actions = (await page.locator('.analysis-header__actions').boundingBox())!
  expect(actions.y - title.y, 'the buttons sit in the first row of the title').toBeLessThan(10)
  await snapshot(page, 'header-03-many-tags', { fullPage: false })
})

test('export-header-long-filename-and-many-tags', async ({ page }) => {
  const annotations = analysisAnnotations({ tags: MANY_TAGS.map((name) => tag(name)) })
  await openAnalysis(page, { ...FINISHED_ANALYSIS, filename: LONG_FILENAME, tags: MANY_TAGS }, { annotations })
  await expect(page.locator('.analysis-header .tag-chip').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'header-03b-long-filename-many-tags', { fullPage: false })
})

test('export-header-menu-narrow-800', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 700 })
  await openAnalysis(page)
  await openHeaderMenu(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'header-04-menu-narrow-800', { fullPage: false })
})

test('export-header-menu-narrow-800-unfinished', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 700 })
  await openAnalysis(page, RUNNING_ANALYSIS)
  await openHeaderMenu(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'header-05-menu-narrow-800-unfinished', { fullPage: false })
})

// ---------- IOC downloads ----------

test('export-ioc-download-saves-the-file-and-confirms', async ({ page }) => {
  const exports = await openAnalysis(page)
  await openHeaderMenu(page)
  const downloading = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: 'CSV' }).or(page.locator('.export-entries .q-item', { hasText: 'CSV' })).click()
  const download = await downloading
  expect(download.suggestedFilename()).toBe(`tartarus-${ANALYSIS_ID}-iocs.csv`)
  expect(exports.iocRequests()).toEqual(['csv'])
  await expect(page.locator('.tt-toast--success')).toContainText('CSV IOCs downloaded')
  await expect(page.locator('.export-entries')).toBeHidden()
  await snapshot(page, 'ioc-01-downloaded-toast', { fullPage: false, toast: true })
})

test('export-ioc-download-preparing-toast', async ({ page }) => {
  await openAnalysis(page, FINISHED_ANALYSIS, { iocDelayMs: 4000 })
  await openHeaderMenu(page)
  await page.locator('.export-entries .q-item', { hasText: 'STIX 2.1' }).click()
  await expect(page.locator('.tt-toast--info')).toContainText('Preparing the STIX 2.1 IOCs')
  await expect(page.locator('.export-entries')).toBeHidden()
  await snapshot(page, 'ioc-02-preparing-toast', { fullPage: false, toast: true })
})

test('export-ioc-download-error-toast', async ({ page }) => {
  await openAnalysis(page, FINISHED_ANALYSIS, {
    iocReply: { status: 500, body: errorEnvelope('internal_error', 'The IOC export failed: the event index is unavailable') },
  })
  await openHeaderMenu(page)
  await page.locator('.export-entries .q-item', { hasText: 'MISP' }).click()
  await expect(page.locator('.tt-toast--error')).toContainText('The IOC export failed')
  await expect(page.locator('.tt-toast--info')).toHaveCount(0)
  await expect(page.locator('.export-entries')).toBeHidden()
  await snapshot(page, 'ioc-03-error-toast', { fullPage: false, toast: true })
})

// ---------- Dashboard row menu ----------

test('export-dashboard-row-menu-done', async ({ page }) => {
  await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 6)
  await expect(page.locator('.row-menu > .q-item .q-item__section--main')).toHaveText(['Open', 'Re-ingest', 'Export', 'Delete'])
  await snapshot(page, 'dashboard-01-row-menu-done')
})

test('export-dashboard-row-menu-running', async ({ page }) => {
  await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 8)
  await expect(page.locator('.row-menu > .q-item .q-item__section--main')).toHaveText(['Open', 'Export', 'Cancel'])
  await snapshot(page, 'dashboard-02-row-menu-running')
})

test('export-dashboard-row-menu-failed', async ({ page }) => {
  await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 3)
  await expect(page.locator('.row-menu > .q-item .q-item__section--main')).toHaveText(['Open', 'Export', 'Delete'])
  await snapshot(page, 'dashboard-03-row-menu-failed')
})

test('export-dashboard-export-submenu-done', async ({ page }) => {
  await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 6)
  await page.locator('.row-menu > .q-item', { hasText: 'Export' }).click()
  await expect(page.locator('.export-entries')).toBeVisible()
  await expect(page.locator('.export-entries__hint')).toHaveCount(0)
  await snapshot(page, 'dashboard-04-export-submenu-done')
})

test('export-dashboard-export-submenu-running-reports-disabled', async ({ page }) => {
  await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 8)
  await page.locator('.row-menu > .q-item', { hasText: 'Export' }).click()
  await expect(page.locator('.export-entries__hint')).toBeVisible()
  await snapshot(page, 'dashboard-05-export-submenu-running')
})

test('export-dashboard-row-menu-narrow-800', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 700 })
  await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 6)
  await page.locator('.row-menu > .q-item', { hasText: 'Export' }).click()
  await expect(page.locator('.export-entries')).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'dashboard-06-row-menu-narrow-800', { fullPage: false })
})

test('export-dashboard-ioc-download-from-the-row-menu', async ({ page }) => {
  const exports = await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 6)
  await page.locator('.row-menu > .q-item', { hasText: 'Export' }).click()
  const downloading = page.waitForEvent('download')
  await page.locator('.export-entries .q-item', { hasText: 'STIX 2.1' }).click()
  expect((await downloading).suggestedFilename()).toBe(`tartarus-${ANALYSIS_ID}-iocs.stix.json`)
  expect(exports.iocRequests()).toEqual(['stix'])
})

test('export-dashboard-report-entry-opens-the-dialog', async ({ page }) => {
  await openDashboard(page, MIXED_ANALYSES)
  await openRowMenu(page, 6)
  await page.locator('.row-menu > .q-item', { hasText: 'Export' }).click()
  await page.locator('.export-entries .q-item', { hasText: 'PDF' }).click()
  await expect(page.locator('.report-dialog')).toBeVisible()
  await expect(page.locator('.report-dialog__title')).toContainText('#6')
})
