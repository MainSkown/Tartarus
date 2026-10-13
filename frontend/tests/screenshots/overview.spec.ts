import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  NARROW_AND_WIDE_WIDTHS,
  errorEnvelope,
  expect,
  expectNoHorizontalOverflow,
  makeDetectedAnalysis,
  mockAnalyses,
  mockShell,
  mockViews,
  realView,
  screenshotPath,
  test,
  waitForTransitions,
  type ViewMock,
  type ViewName,
} from './fixtures'

const ID = 45
const LANE_COUNTS = { api: 472, network: 217, process: 15, file: 2, registry: 2 }

function analysisWithLanes(): AnalysisRead {
  const analysis = makeDetectedAnalysis({ id: ID })
  return { ...analysis, summary: { ...analysis.summary, lane_counts: LANE_COUNTS } }
}

async function openOverview(page: Page, overrides: Partial<Record<ViewName, ViewMock>> = {}): Promise<void> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysisWithLanes()] })
  await mockViews(page, overrides)
  await page.goto(`/analyses/${ID}`)
}

function lightboxImage(page: Page, alt: string) {
  return page.locator(`.screenshot-lightbox__image[alt="${alt}"]`)
}

async function waitForThumbnails(page: Page): Promise<void> {
  await expect(page.locator('.screenshot-strip__thumb').first()).toBeVisible()
  await page.waitForFunction(() =>
    [...document.querySelectorAll<HTMLImageElement>('.screenshot-strip__thumb img')]
      .filter((image) => image.getBoundingClientRect().left < window.innerWidth)
      .every((image) => image.complete && image.naturalWidth > 0),
  )
}

test('overview-lanes-and-screenshots', async ({ page }) => {
  await openOverview(page)
  await expect(page.locator('.lane-bar')).toHaveCount(5)
  await waitForThumbnails(page)
  await page.screenshot({ path: screenshotPath('overview-lanes-and-screenshots'), fullPage: true })
})

test('overview-lightbox-open', async ({ page }) => {
  await openOverview(page)
  await waitForThumbnails(page)
  await page.locator('.screenshot-strip__thumb').nth(2).click()
  await expect(lightboxImage(page, 'Screenshot 3 of 10')).toBeVisible()
  await page.waitForFunction(() => {
    const image = document.querySelector<HTMLImageElement>('.screenshot-lightbox__image')
    return image !== null && image.complete && image.naturalWidth > 0
  })
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('overview-lightbox-open') })
})

test('overview-lightbox-keyboard-navigation', async ({ page }) => {
  await openOverview(page)
  await waitForThumbnails(page)
  await page.locator('.screenshot-strip__thumb').first().click()
  await expect(lightboxImage(page, 'Screenshot 1 of 10')).toBeVisible()
  await page.keyboard.press('ArrowRight')
  await expect(lightboxImage(page, 'Screenshot 2 of 10')).toBeVisible()
  await page.keyboard.press('ArrowLeft')
  await page.keyboard.press('ArrowLeft')
  await expect(lightboxImage(page, 'Screenshot 1 of 10')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Previous screenshot' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(page.locator('.screenshot-lightbox')).toHaveCount(0)
})

test('overview-screenshots-error', async ({ page }) => {
  await openOverview(page, { artifacts: { status: 500, body: errorEnvelope('internal_error', 'artifact index unavailable') } })
  await expect(page.getByText('failed to load: artifact index unavailable')).toBeVisible()
  await expect(page.locator('.lane-bar')).toHaveCount(5)
  await page.screenshot({ path: screenshotPath('overview-screenshots-error'), fullPage: true })
})

test('overview-no-screenshots', async ({ page }) => {
  await openOverview(page, { artifacts: { body: { ...realView<object>('artifacts'), screenshots: [] } } })
  await expect(page.getByText('> no screenshots were captured')).toBeVisible()
  await page.screenshot({ path: screenshotPath('overview-no-screenshots'), fullPage: true })
})

test('overview-screenshots-loading', async ({ page }) => {
  await openOverview(page, { artifacts: { delayMs: 3000 } })
  await expect(page.locator('.analysis-summary .loader')).toBeVisible()
  await page.screenshot({ path: screenshotPath('overview-screenshots-loading'), fullPage: true })
})

test('overview-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  await openOverview(page)
  await waitForThumbnails(page)
  await page.screenshot({ path: screenshotPath('overview-narrow-600'), fullPage: true })
})

test('overview-lightbox-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  await openOverview(page)
  await waitForThumbnails(page)
  await page.locator('.screenshot-strip__thumb').first().click()
  await expect(lightboxImage(page, 'Screenshot 1 of 10')).toBeVisible()
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('overview-lightbox-narrow-600') })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`overview does not scroll sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openOverview(page)
    await waitForThumbnails(page)
    await expectNoHorizontalOverflow(page)
    await page.locator('.screenshot-strip__thumb').first().click()
    await expect(page.locator('.screenshot-lightbox__image')).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })
}
