import type { Page } from '@playwright/test'
import type { AnalysisRead, Artifact, MemorySummary } from '../../src/api/types.gen'
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
import {
  BOTH_PLUGINS,
  DUMP,
  ID,
  LONG_VALUES,
  MANY,
  MEMORY,
  UNKNOWN_PLUGIN,
  artifactsWithDump,
  mockMemoryEvents,
  type MemoryMock,
} from './artifacts-memory-data'
import { analysisWithSources } from './overview-sources-data'

interface Scenario {
  memory: MemorySummary | null
  dump?: Artifact | null
  events?: MemoryMock
  artifactsDelayMs?: number
}

async function openMemory(page: Page, { memory, dump = null, events, artifactsDelayMs }: Scenario): Promise<void> {
  const analysis: AnalysisRead = analysisWithSources({ memory })
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockViews(page, { artifacts: { body: artifactsWithDump(dump), delayMs: artifactsDelayMs } })
  await mockMemoryEvents(page, events)
  await page.goto(`/analyses/${ID}/artifacts`)
  const tabs = page.locator('.artifact-sub-tabs')
  await expect(tabs.getByRole('tab').first()).toBeVisible()
  await tabs.getByRole('tab', { name: /^MEMORY/ }).click()
  await waitForTransitions(page)
}

const panel = (page: Page) => page.locator('.artifact-panel:visible')

async function settled(page: Page): Promise<void> {
  await expect(panel(page).locator('.loader, [aria-busy="true"]')).toHaveCount(0)
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
}

async function shoot(page: Page, name: string, fullPage = true): Promise<void> {
  // The app bar is fixed: a page scrolled down by a click would show it again in the middle of a full-page capture.
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: screenshotPath(`artifacts-memory-${name}`), fullPage })
}

const KEPT: Scenario = { memory: MEMORY.kept, dump: DUMP }

test.describe('findings and dump', () => {
  test('findings-both-plugins', async ({ page }) => {
    await openMemory(page, KEPT)
    await expect(panel(page).locator('.finding-group__name')).toHaveText(['malfind', 'hollowprocesses'])
    await expect(page.locator('.artifact-sub-tabs').getByRole('tab', { name: 'MEMORY (5)' })).toBeVisible()
    await settled(page)
    await shoot(page, 'findings-both-plugins')
  })

  test('expanded-finding', async ({ page }) => {
    await openMemory(page, KEPT)
    await panel(page).locator('.finding-toggle').first().click()
    await expect(panel(page).locator('.hex-row')).toHaveCount(4)
    await panel(page).locator('.finding-group').nth(1).locator('.finding-toggle').first().click()
    await expect(panel(page).getByText('this plugin does not read the bytes')).toBeVisible()
    await settled(page)
    await shoot(page, 'expanded-finding')
  })

  test('dump-kept', async ({ page }) => {
    await openMemory(page, KEPT)
    await settled(page)
    await page.locator('.memory-dump').screenshot({ path: screenshotPath('artifacts-memory-dump-kept') })
  })

  test('dump-kept-not-on-disk', async ({ page }) => {
    await openMemory(page, { memory: MEMORY.kept, dump: { ...DUMP, downloadable: false } })
    await settled(page)
    await page.locator('.memory-dump').screenshot({ path: screenshotPath('artifacts-memory-dump-not-on-disk') })
  })

  test('dump-deleted', async ({ page }) => {
    await openMemory(page, { memory: MEMORY.deleted })
    await expect(panel(page).getByText('deleted after the findings')).toBeVisible()
    await settled(page)
    await shoot(page, 'dump-deleted')
  })

  test('dump-delete-failed', async ({ page }) => {
    await openMemory(page, { memory: MEMORY.deleteFailed, dump: DUMP })
    await settled(page)
    await shoot(page, 'dump-delete-failed')
  })

  test('partial-findings', async ({ page }) => {
    await openMemory(page, { memory: MEMORY.partial, dump: DUMP })
    await expect(panel(page).locator('.memory-findings__note')).toBeVisible()
    await settled(page)
    await shoot(page, 'partial-findings')
  })

  test('unknown-plugin', async ({ page }) => {
    await openMemory(page, { ...KEPT, events: { events: UNKNOWN_PLUGIN } })
    await expect(panel(page).locator('.finding-group__name')).toHaveText(['malfind', 'hollowprocesses', 'SSDT'])
    await settled(page)
    await shoot(page, 'unknown-plugin')
  })
})

test.describe('states', () => {
  test('none-requested', async ({ page }) => {
    await openMemory(page, { memory: null })
    await expect(panel(page).getByText('no memory dump was requested')).toBeVisible()
    await settled(page)
    await shoot(page, 'none-requested')
  })

  test('no-findings', async ({ page }) => {
    await openMemory(page, { memory: MEMORY.deleted, events: { events: [] } })
    await expect(panel(page).getByText('found no injected or hollowed processes')).toBeVisible()
    await settled(page)
    await shoot(page, 'no-findings')
  })

  test('unavailable', async ({ page }) => {
    await openMemory(page, { memory: MEMORY.unavailable })
    await expect(panel(page).getByText('no findings: there was no dump to read')).toBeVisible()
    await settled(page)
    await shoot(page, 'unavailable')
  })

  test('failed-dump-kept', async ({ page }) => {
    await openMemory(page, { memory: MEMORY.failed, dump: DUMP })
    await expect(panel(page).getByText('The dump itself is still there')).toBeVisible()
    await settled(page)
    await shoot(page, 'failed-dump-kept')
  })

  test('failed-dump-deleted', async ({ page }) => {
    await openMemory(page, { memory: { ...MEMORY.failed, dump_deleted: true } })
    await expect(panel(page).getByText('findings failed')).toBeVisible()
    await settled(page)
    await shoot(page, 'failed-dump-deleted')
  })

  test('loading', async ({ page }) => {
    await openMemory(page, { ...KEPT, events: { searchDelayMs: 5000 } })
    await expect(panel(page).locator('[aria-busy="true"]')).toBeVisible()
    await shoot(page, 'loading')
  })

  test('loading-artifacts', async ({ page }) => {
    await openMemory(page, { memory: null, artifactsDelayMs: 5000 })
    await expect(panel(page).locator('.loader')).toBeVisible()
    await shoot(page, 'loading-artifacts')
  })

  test('error-loading-events', async ({ page }) => {
    await openMemory(page, { ...KEPT, events: { searchStatus: 502 } })
    await expect(panel(page).getByRole('button', { name: '[RETRY]' })).toBeVisible()
    await settled(page)
    await shoot(page, 'error-loading-events')
  })
})

test.describe('many and long', () => {
  test('60-findings', async ({ page }) => {
    await openMemory(page, { ...KEPT, events: { events: MANY } })
    await expect(panel(page).locator('tr.finding-row')).toHaveCount(25)
    await expect(page.locator('.artifact-sub-tabs').getByRole('tab', { name: 'MEMORY (60)' })).toBeVisible()
    await settled(page)
    await shoot(page, '60-findings')
    await panel(page).locator('.finding-group__more').click()
    await expect(panel(page).locator('tr.finding-row')).toHaveCount(50)
    await shoot(page, '60-findings-shown-more')
  })

  test('truncated', async ({ page }) => {
    await openMemory(page, { ...KEPT, events: { events: MANY.slice(0, 10), total: 1342 } })
    await expect(panel(page).getByText('Showing 10 of 1342 findings')).toBeVisible()
    await settled(page)
    await shoot(page, 'truncated')
  })

  test('long-values', async ({ page }) => {
    await openMemory(page, { ...KEPT, events: { events: LONG_VALUES } })
    await settled(page)
    await shoot(page, 'long-values')
    await panel(page).locator('.finding-toggle').first().click()
    await expect(panel(page).locator('.hex-row')).toHaveCount(4)
    await settled(page)
    await shoot(page, 'long-values-expanded')
  })
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`width-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openMemory(page, { ...KEPT, events: { events: [...BOTH_PLUGINS, ...LONG_VALUES.slice(0, 3)] } })
    await settled(page)
    await shoot(page, `width-${width}`)
    await panel(page).locator('.finding-toggle').first().click()
    await expect(panel(page).locator('.hex-row')).toHaveCount(4)
    await settled(page)
    await shoot(page, `width-${width}-expanded`)
  })
}

test('width-600-deleted-and-unavailable', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  await openMemory(page, { memory: MEMORY.unavailable })
  await settled(page)
  await shoot(page, 'width-600-unavailable')
})
