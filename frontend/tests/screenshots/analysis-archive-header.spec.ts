import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  makeAnalysis,
  makeDetectedAnalysis,
  mockAnalyses,
  mockShell,
  mockViews,
  screenshotPath,
  sha256Of,
  test,
  waitForTransitions,
} from './fixtures'

const ID = 7
const ENTRY_SHA256 = sha256Of(0xe5)
const LONG_ZIP_NAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(60)}.zip`
const LONG_ENTRY = `${'nested_directory_with_a_long_name/'.repeat(5)}quarterly_financial_report_final_FINAL_v2.pdf.exe`

test.use({ timezoneId: 'UTC' })

function archiveOptions(entry: string): AnalysisRead['options'] {
  return { route: 'inetsim', timeout: 180, package: 'zip', archive_entry: entry }
}

function finishedArchive(entry: string, entrySha256: string | null, filename = 'invoice_bundle.zip'): AnalysisRead {
  const base = makeDetectedAnalysis({ id: ID, filename, options: archiveOptions(entry) })
  return { ...base, summary: { ...base.summary!, sample: { name: entry, type: 'PE32 executable', entry_sha256: entrySha256 } } }
}

async function openHeader(page: Page, analysis: AnalysisRead, width = 1280): Promise<void> {
  await page.setViewportSize({ width, height: 520 })
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  if (analysis.status === 'done') await mockViews(page)
  await page.goto(`/analyses/${ID}/summary`)
  await expect(page.locator('.analysis-header__filename')).toHaveText(analysis.filename)
  await waitForTransitions(page)
}

async function expectRowsToShare(page: Page, selector: string): Promise<void> {
  const lefts = await page.locator(selector).evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().left)))
  expect(new Set(lefts).size, `${selector} starts at ${lefts.join(', ')}`).toBe(1)
}

test('analysis-archive-header-done', async ({ page }) => {
  await openHeader(page, finishedArchive('payload/loader.exe', ENTRY_SHA256))
  await expect(page.locator('.hash-row__label')).toHaveText(['ARCHIVE SHA-256', 'FILE SHA-256'])
  await expect(page.locator('.analysis-header__entry')).toHaveText('payload/loader.exe')
  await expect(page.locator('.hash-row__hash').last()).toHaveText(ENTRY_SHA256)
  await expectRowsToShare(page, '.hash-row__hash, .analysis-header__entry')
  await page.screenshot({ path: screenshotPath('analysis-archive-header-done') })
})

test('analysis-archive-header-running', async ({ page }) => {
  const analysis = makeAnalysis({ id: ID, status: 'running', started_at: '2026-10-12T09:14:30Z', options: archiveOptions('payload/loader.exe'), filename: 'invoice_bundle.zip' })
  await openHeader(page, analysis)
  await expect(page.locator('.hash-row__absent')).toHaveText('NOT RECORDED')
  await expect(page.locator('.hash-row__absent')).toHaveAttribute('title', 'The hash appears when the run is finished.')
  await page.screenshot({ path: screenshotPath('analysis-archive-header-running') })
})

test('analysis-archive-header-no-entry-hash', async ({ page }) => {
  await openHeader(page, finishedArchive('plugins/helper.dll', null))
  await expect(page.locator('.hash-row__absent')).toHaveAttribute('title', /started no process of its own/)
  await page.screenshot({ path: screenshotPath('analysis-archive-header-no-entry-hash') })
})

test('analysis-archive-header-long', async ({ page }) => {
  await openHeader(page, finishedArchive(LONG_ENTRY, ENTRY_SHA256, LONG_ZIP_NAME))
  await expect(page.locator('.analysis-header__entry')).toHaveAttribute('title', LONG_ENTRY)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('analysis-archive-header-long') })
})

test('analysis-archive-header-narrow-360', async ({ page }) => {
  await openHeader(page, finishedArchive('payload/loader.exe', ENTRY_SHA256), 360)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('analysis-archive-header-narrow-360'), fullPage: true })
})

test('analysis-archive-header-narrow-360-long', async ({ page }) => {
  await openHeader(page, finishedArchive(LONG_ENTRY, ENTRY_SHA256, LONG_ZIP_NAME), 360)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath('analysis-archive-header-narrow-360-long'), fullPage: true })
})

test('analysis-archive-header-plain-sample', async ({ page }) => {
  await openHeader(page, makeDetectedAnalysis({ id: ID, filename: 'invoice_scan.exe' }))
  await expect(page.locator('.hash-row__label')).toHaveText(['SHA-256'])
  await expect(page.locator('.analysis-header__entry-row')).toHaveCount(0)
  await page.screenshot({ path: screenshotPath('analysis-archive-header-plain-sample') })
})
