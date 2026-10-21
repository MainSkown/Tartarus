import type { Page } from '@playwright/test'
import {
  NARROW_AND_WIDE_WIDTHS,
  expect,
  expectNoHorizontalOverflow,
  mockQuery,
  mockShell,
  screenshotPath,
  test,
  waitForTransitions,
} from './fixtures'
import { SEARCH_FAILURE, mockSearch, pagedHits, severalAnalysesHits, type SearchMockOptions } from './search-data'

const QUERY = 'process.name:powershell.exe'

async function openSearch(page: Page, options: SearchMockOptions = {}) {
  await mockShell(page)
  await mockQuery(page)
  const mock = await mockSearch(page, options)
  await page.goto('/search')
  await expect(page.getByRole('combobox', { name: 'Query' })).toBeVisible()
  return mock
}

async function runQuery(page: Page, text: string = QUERY): Promise<void> {
  const bar = page.getByRole('combobox', { name: 'Query' })
  await bar.click()
  await bar.pressSequentially(text)
  await bar.press('Escape')
  await bar.press('Enter')
}

/** A state that lists rows needs a results area tall enough to show them; a zero-height one clips every row out of sight. */
async function expectTableHasRoom(page: Page): Promise<void> {
  const box = await page.locator('.search-page__results').boundingBox()
  expect(box?.height ?? 0, 'the results area is too short to show anything').toBeGreaterThan(100)
}

async function settled(page: Page): Promise<void> {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
}

async function shoot(page: Page, name: string): Promise<void> {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: screenshotPath(`search-${name}`), fullPage: true })
}

test('search-initial-hint', async ({ page }) => {
  await openSearch(page)
  await expect(page.getByText('Type a query and press Enter')).toBeVisible()
  await waitForTransitions(page)
  await expectNoHorizontalOverflow(page)
  await shoot(page, 'initial-hint')
})

test('search-loading', async ({ page }) => {
  await openSearch(page, { hits: severalAnalysesHits(), delayMs: 5000 })
  await runQuery(page)
  await expect(page.locator('[aria-busy="true"]')).toBeAttached()
  await waitForTransitions(page)
  await shoot(page, 'loading')
  await expectTableHasRoom(page)
})

test('search-empty-result', async ({ page }) => {
  await openSearch(page, { hits: [] })
  await runQuery(page)
  await expect(page.locator('.event-table__empty')).toBeVisible()
  await settled(page)
  await shoot(page, 'empty-result')
})

test('search-error', async ({ page }) => {
  await openSearch(page, { failure: SEARCH_FAILURE })
  await runQuery(page)
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await settled(page)
  await shoot(page, 'error')
})

test('search-results-several-analyses', async ({ page }) => {
  const mock = await openSearch(page, { hits: severalAnalysesHits() })
  await runQuery(page)
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await expect(page.locator('.search-page__analysis').first()).toBeVisible()
  await settled(page)
  expect(mock.requests.at(-1)?.query).toBe(QUERY)
  await shoot(page, 'results')
  await expectTableHasRoom(page)
})

test('search-results-next-cursor', async ({ page }) => {
  const mock = await openSearch(page, { hits: pagedHits(), total: 250 })
  await runQuery(page)
  await expect(page.locator('.search-page__analysis').first()).toBeVisible()
  await expect(page.locator('.event-table__count')).toContainText('250')
  await settled(page)
  expect(mock.requests).toHaveLength(1)
  await shoot(page, 'results-next-cursor')
  await expectTableHasRoom(page)
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`search-width-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openSearch(page, { hits: severalAnalysesHits() })
    await shoot(page, `width-${width}-initial`)
    await runQuery(page)
    await expect(page.locator('.search-page__analysis').first()).toBeVisible()
    await settled(page)
    await shoot(page, `width-${width}-results`)
    await expectTableHasRoom(page)
  })
}
