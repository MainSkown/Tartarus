import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  expectNoVerticalScroll,
  mockAnalyses,
  mockEvents,
  mockQuery,
  mockShell,
  mockViews,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import {
  DEFENDER_WARNING,
  ID,
  LONG_WARNING,
  SYSMON_WARNING,
  analysisWithWarnings,
} from './analysis-warnings-data'

const SUMMARY_PATH = `/analyses/${ID}/summary`
const EVENTS_PATH = `/analyses/${ID}/events`
const TWO_WARNINGS = [SYSMON_WARNING, DEFENDER_WARNING]
const NARROW_WIDTH = 600

async function openAnalysis(page: Page, analysis: AnalysisRead, path: string): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockViews(page)
  await mockQuery(page)
  await mockEvents(page)
  await page.goto(path)
}

async function openSummary(page: Page, analysis: AnalysisRead): Promise<void> {
  await openAnalysis(page, analysis, SUMMARY_PATH)
  await expect(page.locator('.analysis-summary__tiles').first()).toBeVisible()
}

async function openEvents(page: Page, analysis: AnalysisRead): Promise<void> {
  await openAnalysis(page, analysis, EVENTS_PATH)
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
}

async function snapshotSummary(page: Page, name: string): Promise<void> {
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

/** The Events tab fills the viewport and its table scrolls inside itself, so neither the page nor the table's bottom may leave the window. */
async function snapshotEvents(page: Page, name: string): Promise<void> {
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
  await expectNoVerticalScroll(page)
  const { tableBottom, viewportHeight } = await page.evaluate(() => ({
    tableBottom: document.querySelector('.events-tab__table')?.getBoundingClientRect().bottom ?? 0,
    viewportHeight: window.innerHeight,
  }))
  expect(tableBottom, 'events table runs past the bottom of the window').toBeLessThanOrEqual(viewportHeight)
  await page.screenshot({ path: screenshotPath(name) })
}

test('analysis-warnings-summary-one-warning-route-analysis-summary', async ({ page }) => {
  await openSummary(page, analysisWithWarnings([SYSMON_WARNING]))
  await expect(page.locator('.analysis-warnings li')).toHaveCount(1)
  await snapshotSummary(page, 'analysis-warnings-summary-one-warning-route-analysis-summary')
})

test('analysis-warnings-summary-two-warnings-route-analysis-summary', async ({ page }) => {
  await openSummary(page, analysisWithWarnings(TWO_WARNINGS))
  await expect(page.locator('.analysis-warnings li')).toHaveCount(2)
  await snapshotSummary(page, 'analysis-warnings-summary-two-warnings-route-analysis-summary')
})

test('analysis-warnings-summary-no-warnings-route-analysis-summary', async ({ page }) => {
  await openSummary(page, analysisWithWarnings())
  await expect(page.locator('.analysis-warnings')).toHaveCount(0)
  await snapshotSummary(page, 'analysis-warnings-summary-no-warnings-route-analysis-summary')
})

test('analysis-warnings-summary-long-warning-route-analysis-summary', async ({ page }) => {
  await openSummary(page, analysisWithWarnings([LONG_WARNING, DEFENDER_WARNING]))
  await expect(page.locator('.analysis-warnings li')).toHaveCount(2)
  await snapshotSummary(page, 'analysis-warnings-summary-long-warning-route-analysis-summary')
})

test('analysis-warnings-summary-two-warnings-narrow-600px-route-analysis-summary', async ({ page }) => {
  await page.setViewportSize({ width: NARROW_WIDTH, height: 900 })
  await openSummary(page, analysisWithWarnings([LONG_WARNING, DEFENDER_WARNING]))
  await expect(page.locator('.analysis-warnings li')).toHaveCount(2)
  await snapshotSummary(page, 'analysis-warnings-summary-two-warnings-narrow-600px-route-analysis-summary')
})

test('analysis-warnings-events-two-warnings-route-analysis-events', async ({ page }) => {
  await openEvents(page, analysisWithWarnings(TWO_WARNINGS))
  await expect(page.locator('.analysis-warnings li')).toHaveCount(2)
  await snapshotEvents(page, 'analysis-warnings-events-two-warnings-route-analysis-events')
})

test('analysis-warnings-events-no-warnings-route-analysis-events', async ({ page }) => {
  await openEvents(page, analysisWithWarnings())
  await expect(page.locator('.analysis-warnings')).toHaveCount(0)
  await snapshotEvents(page, 'analysis-warnings-events-no-warnings-route-analysis-events')
})

test('analysis-warnings-events-two-warnings-narrow-600px-route-analysis-events', async ({ page }) => {
  await page.setViewportSize({ width: NARROW_WIDTH, height: 900 })
  await openEvents(page, analysisWithWarnings([LONG_WARNING, DEFENDER_WARNING]))
  await expect(page.locator('.analysis-warnings li')).toHaveCount(2)
  await snapshotEvents(page, 'analysis-warnings-events-two-warnings-narrow-600px-route-analysis-events')
})
