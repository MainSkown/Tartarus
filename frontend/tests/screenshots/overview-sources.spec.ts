import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  NARROW_AND_WIDE_WIDTHS,
  expect,
  expectNoHorizontalOverflow,
  mockAnalyses,
  mockShell,
  mockViews,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import { DEFENDER, HIDDEN_EVENTS, ID, MEMORY, analysisWithSources, emptyRunAnalysis, oldSummaryAnalysis } from './overview-sources-data'

async function openOverview(page: Page, analysis: AnalysisRead): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockViews(page)
  await page.goto(`/analyses/${ID}`)
  await expect(page.locator('.lane-bar').first()).toBeVisible()
  await page.waitForFunction(() =>
    [...document.querySelectorAll<HTMLImageElement>('.screenshot-strip__thumb img')]
      .filter((image) => image.getBoundingClientRect().left < window.innerWidth)
      .every((image) => image.complete && image.naturalWidth > 0),
  )
}

const VERDICT_STATES: [string, AnalysisRead][] = [
  ['defender-removed-dropped', analysisWithSources({ defender: DEFENDER.removedDropped })],
  ['defender-removed-sample', analysisWithSources({ defender: DEFENDER.removedSample })],
  ['defender-detected', analysisWithSources({ defender: DEFENDER.detected })],
  ['defender-failed', analysisWithSources({ defender: DEFENDER.failed })],
  ['defender-clean', analysisWithSources({ defender: DEFENDER.clean })],
  ['defender-no-export', analysisWithSources({ defender: DEFENDER.noExport })],
  ['defender-off-guest', analysisWithSources({ defender: DEFENDER.clean, badges: ['DEFENDER OFF', 'SYSMON'] })],
  ['defender-long-values', analysisWithSources({ defender: DEFENDER.longValues })],
  ['defender-many-threats', analysisWithSources({ defender: DEFENDER.many })],
]

for (const [name, analysis] of VERDICT_STATES) {
  test(`overview-sources-${name}`, async ({ page }) => {
    await openOverview(page, analysis)
    if (name === 'defender-off-guest') await expect(page.locator('.defender-verdict')).toHaveCount(0)
    else await expect(page.locator('.defender-verdict')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: screenshotPath(`overview-sources-${name}`), fullPage: true })
  })
}

test('overview-sources-defender-blocked-before-run', async ({ page }) => {
  await openOverview(page, emptyRunAnalysis())
  await expect(page.locator('.defender-verdict--prominent')).toBeVisible()
  await page.screenshot({ path: screenshotPath('overview-sources-defender-blocked-before-run'), fullPage: true })
})

test('overview-sources-hidden-events', async ({ page }) => {
  await openOverview(page, analysisWithSources({ hidden_events: HIDDEN_EVENTS }))
  await page.locator('.hidden-events').hover()
  await expect(page.locator('.q-tooltip')).toBeVisible()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('overview-sources-hidden-events') })
})

for (const state of ['ok', 'unavailable', 'failed', 'kept'] as const) {
  test(`overview-sources-memory-${state}`, async ({ page }) => {
    await openOverview(page, analysisWithSources({ memory: MEMORY[state] }))
    await expect(page.locator('.memory-status')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: screenshotPath(`overview-sources-memory-${state}`), fullPage: true })
  })
}

test('overview-sources-old-summary', async ({ page }) => {
  await openOverview(page, oldSummaryAnalysis())
  await expect(page.locator('.defender-verdict, .hidden-events, .memory-status')).toHaveCount(0)
  await page.screenshot({ path: screenshotPath('overview-sources-old-summary'), fullPage: true })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`overview-sources-everything-${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openOverview(
      page,
      analysisWithSources({ defender: DEFENDER.longValues, hidden_events: HIDDEN_EVENTS, memory: MEMORY.failed }),
    )
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: screenshotPath(`overview-sources-everything-${width}px`), fullPage: true })
  })

  test(`overview-sources-blocked-before-run-${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openOverview(page, emptyRunAnalysis())
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: screenshotPath(`overview-sources-blocked-before-run-${width}px`), fullPage: true })
  })
}
