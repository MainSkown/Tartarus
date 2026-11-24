import type { Page } from '@playwright/test'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  mockAnalyses,
  mockEvents,
  mockQuery,
  mockShell,
  mockViews,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import { ANALYSIS_STATES, ID, analysisWithLan } from './summary-lateral-movement-data'
import type { LanSummary } from '../../src/api/types.gen'

const SUMMARY_PATH = `/analyses/${ID}/summary`
const NARROW_WIDTH = 360

async function openSummary(page: Page, lan: LanSummary | undefined): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysisWithLan(lan)] })
  await mockViews(page)
  await mockQuery(page)
  await mockEvents(page)
  await page.goto(SUMMARY_PATH)
  await expect(page.locator('.analysis-summary__tiles').first()).toBeVisible()
}

/** The app scrolls inside its own container, so a card whose text pokes out never trips the page-level check. */
async function expectHostsContainTheirContent(page: Page): Promise<void> {
  const overflowing = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('.lan-host')]
      .filter((card) => card.scrollWidth > card.clientWidth)
      .map((card) => card.querySelector('h3')?.textContent ?? ''),
  )
  expect(overflowing, 'host cards whose content runs past their border').toEqual([])
}

async function snapshot(page: Page, name: string): Promise<void> {
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
  await expectHostsContainTheirContent(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

test('summary-lateral-movement-hidden-feature-off-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.hidden)
  await expect(page.getByText('LATERAL MOVEMENT')).toHaveCount(0)
  await snapshot(page, 'summary-lateral-movement-hidden-feature-off-route-analysis-summary')
})

test('summary-lateral-movement-empty-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.empty)
  await expect(page.getByText('the sample did nothing on the fake local network')).toBeVisible()
  await snapshot(page, 'summary-lateral-movement-empty-route-analysis-summary')
})

test('summary-lateral-movement-one-host-one-service-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.oneService)
  await expect(page.locator('.lan-host')).toHaveCount(1)
  await snapshot(page, 'summary-lateral-movement-one-host-one-service-route-analysis-summary')
})

test('summary-lateral-movement-three-hosts-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.threeHosts)
  await expect(page.locator('.lan-host')).toHaveCount(3)
  await snapshot(page, 'summary-lateral-movement-three-hosts-route-analysis-summary')
})

test('summary-lateral-movement-truncated-log-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.truncated)
  await expect(page.getByText('lower bounds')).toBeVisible()
  await snapshot(page, 'summary-lateral-movement-truncated-log-route-analysis-summary')
})

test('summary-lateral-movement-long-values-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.long)
  await expect(page.locator('.lan-file__path')).toBeVisible()
  await snapshot(page, 'summary-lateral-movement-long-values-route-analysis-summary')
})

test('summary-lateral-movement-hostile-strings-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.hostile)
  await expect(page.locator('.lan-summary img, .lan-summary svg, .lan-summary script')).toHaveCount(0)
  await expect(page.locator('.lan-file__path')).toHaveText('<img src=x onerror=alert(1)>')
  await snapshot(page, 'summary-lateral-movement-hostile-strings-route-analysis-summary')
})

test('summary-lateral-movement-more-lines-route-analysis-summary', async ({ page }) => {
  await openSummary(page, ANALYSIS_STATES.more)
  await expect(page.locator('.lan-host__more')).toHaveCount(3)
  await snapshot(page, 'summary-lateral-movement-more-lines-route-analysis-summary')
})

test('summary-lateral-movement-three-hosts-narrow-360px-route-analysis-summary', async ({ page }) => {
  await page.setViewportSize({ width: NARROW_WIDTH, height: 900 })
  await openSummary(page, ANALYSIS_STATES.threeHosts)
  await expect(page.locator('.lan-host')).toHaveCount(3)
  await snapshot(page, 'summary-lateral-movement-three-hosts-narrow-360px-route-analysis-summary')
})

test('summary-lateral-movement-long-values-narrow-360px-route-analysis-summary', async ({ page }) => {
  await page.setViewportSize({ width: NARROW_WIDTH, height: 900 })
  await openSummary(page, ANALYSIS_STATES.long)
  await expect(page.locator('.lan-file__path')).toBeVisible()
  await snapshot(page, 'summary-lateral-movement-long-values-narrow-360px-route-analysis-summary')
})
