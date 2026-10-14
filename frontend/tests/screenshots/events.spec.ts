import type { Locator, Page } from '@playwright/test'
import {
  GUEST_READY_SYSTEM,
  expect,
  expectNoHorizontalOverflow,
  expectNoVerticalScroll,
  makeDetectedAnalysis,
  mockAnalyses,
  mockEvents,
  mockQuery,
  mockShell,
  sampleEventDetails,
  sampleEvents,
  screenshotPath,
  test,
  waitForTransitions,
  type EventsMock,
  type EventsMockOptions,
} from './fixtures'

const ID = 45
const EVENTS_URL = `/analyses/${ID}/events`
const { special } = sampleEventDetails()
const TIMEOUT = { status: 504, code: 'search_timeout', message: 'the search took too long (10 s), narrow the query and try again' }
const HOLD_MS = 120_000

async function openEvents(page: Page, search = '', options: EventsMockOptions = {}): Promise<EventsMock> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockQuery(page)
  const mock = await mockEvents(page, options)
  await page.goto(`${EVENTS_URL}${search ? `?${search}` : ''}`)
  await expect(page.getByRole('combobox', { name: 'Query' })).toBeVisible()
  return mock
}

async function openLoadedEvents(page: Page, search = '', options: EventsMockOptions = {}): Promise<EventsMock> {
  const mock = await openEvents(page, search, options)
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await expect(page.locator('.facet-value').first()).toBeVisible()
  return mock
}

async function capture(page: Page, name: string): Promise<void> {
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`events/${name}`) })
}

async function openDrawer(page: Page, eventId: string, options: EventsMockOptions = {}): Promise<void> {
  await openLoadedEvents(page, `e=${encodeURIComponent(eventId)}`, options)
  await expect(page.locator('.event-detail')).toBeVisible()
}

async function expectContainedHorizontally(page: Page, selector: string): Promise<void> {
  const overflowing = await page.locator(selector).evaluateAll((elements) =>
    elements.filter((element) => element.scrollWidth > element.clientWidth + 1).map((element) => element.className),
  )
  expect(overflowing, `${selector} wider than its box`).toEqual([])
}

function facetValue(page: Page, field: string, value: string): Locator {
  return page.locator('.facet-group', { has: page.locator(`[title="${field}"]`) }).locator('.facet-value', { hasText: value })
}

test('events-a-default-table-loaded', async ({ page }) => {
  await openLoadedEvents(page)
  await expect(page.locator('.event-table__count')).toHaveText('100 of 250 events')
  await expectNoVerticalScroll(page)
  await expectNoHorizontalOverflow(page)
  await capture(page, '01-default-table-loaded-1280x720')
})

test('events-b-loading-skeleton', async ({ page }) => {
  await openEvents(page, '', { searchDelayMs: HOLD_MS, facetsDelayMs: HOLD_MS })
  await expect(page.locator('.event-skeleton-row').first()).toBeVisible()
  await expect(page.locator('.facet-value--skeleton').first()).toBeVisible()
  await expectNoVerticalScroll(page)
  await capture(page, '02-loading-skeleton-table-and-facets')
})

test('events-c-empty-analysis', async ({ page }) => {
  await openEvents(page, '', { events: [] })
  await expect(page.getByText('> no events', { exact: true })).toBeVisible()
  await expect(page.locator('.facet-group__empty').first()).toBeVisible()
  await expectNoVerticalScroll(page)
  await capture(page, '03-empty-analysis-no-events')
})

test('events-d-empty-result-after-filter', async ({ page }) => {
  await openEvents(page, `q=${encodeURIComponent('no-such-word-anywhere')}&f=process.name:cmd.exe`)
  await expect(page.getByText('> no event matches this query')).toBeVisible()
  await expectNoVerticalScroll(page)
  await capture(page, '04-empty-result-with-clear-button')
  await page.locator('.event-table__clear').click()
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await expect(page.locator('.filter-chip')).toHaveCount(0)
})

test('events-e-error-with-retry', async ({ page }) => {
  await openEvents(page, '', { searchFailure: TIMEOUT })
  await expect(page.getByText('failed to load: the search took too long')).toBeVisible()
  await expect(page.getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await expectNoVerticalScroll(page)
  await capture(page, '05-error-with-retry')
})

test('events-e2-facets-failed-table-still-works', async ({ page }) => {
  await openEvents(page, '', { facetsFailure: { status: 502, code: 'search_failed', message: 'search failed' } })
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await expect(page.getByText('facets unavailable: search failed')).toBeVisible()
  await capture(page, '05b-facets-failed-table-unaffected')
})

test('events-f-facet-values-filtered-on-and-out', async ({ page }) => {
  // Both chips are typed with aliases, as a bookmark or the query bar would have them.
  const mock = await openLoadedEvents(page, 'f=lane:api&f=-proc:cmd.exe')
  await expect(page.locator('.filter-chip.is-negated')).toHaveCount(1)
  const laneFacet = page.locator('.facet-group', { has: page.locator('[title="tartarus.lane"]') })
  await expect(laneFacet.locator('.facet-value')).toHaveCount(6)
  await expect(facetValue(page, 'tartarus.lane', 'api')).toHaveClass(/is-included/)
  await expect(facetValue(page, 'process.name', 'cmd.exe')).toHaveClass(/is-excluded/)
  await expect(facetValue(page, 'process.name', 'cmd.exe').locator('.facet-value__count')).toHaveText(/\d+/)
  expect(mock.facetRequests.at(-1)?.filters).toEqual([
    { field: 'lane', value: 'api', negate: false },
    { field: 'proc', value: 'cmd.exe', negate: true },
  ])
  await expectNoVerticalScroll(page)
  await capture(page, '06-facets-alias-chips-included-api-and-excluded-cmd')
})

test('events-f2-facet-click-adds-removes-and-turns-around', async ({ page }) => {
  await openLoadedEvents(page, 'f=proc:cmd.exe')
  await facetValue(page, 'process.name', 'cmd.exe').locator('.facet-value__pick').click()
  await expect(page.locator('.filter-chip')).toHaveCount(0)
  await facetValue(page, 'tartarus.lane', 'file').locator('.facet-value__pick').click({ modifiers: ['Alt'] })
  await expect(page.locator('.filter-chip.is-negated')).toHaveCount(1)
  await expect(facetValue(page, 'tartarus.lane', 'file')).toHaveClass(/is-excluded/)
  await facetValue(page, 'tartarus.lane', 'file').hover()
  await facetValue(page, 'tartarus.lane', 'file').locator('.facet-value__pick').click()
  await expect(page.locator('.filter-chip')).toHaveCount(0)
})

test('events-g-facet-panel-collapsed', async ({ page }) => {
  await openLoadedEvents(page)
  await page.getByRole('button', { name: 'Hide facets' }).click()
  await expect(page.locator('.event-facets')).toHaveClass(/is-collapsed/)
  await expectNoVerticalScroll(page)
  await capture(page, '07-facet-panel-collapsed')
  await page.reload()
  await expect(page.locator('.event-facets')).toHaveClass(/is-collapsed/)
})

const TWELVE_COLUMNS = [
  'process.command_line', 'process.executable', 'process.parent.name', 'file.name', 'file.size', 'registry.hive',
  'registry.value', 'api.arguments', 'api.category', 'destination.port', 'event.module', 'dns.question.type',
]

test('events-h-column-chooser-and-extra-columns', async ({ page }) => {
  const mock = await openLoadedEvents(page)
  await page.getByRole('button', { name: /COLUMNS/ }).click()
  await expect(page.locator('.column-chooser__field').first()).toBeVisible()
  await expect(page.locator('.column-chooser__field', { hasText: 'process.command_line' })).toBeVisible()
  await capture(page, '08-column-chooser-open-every-field')
  await page.getByRole('textbox', { name: 'Find a field' }).fill('process')
  await expect(page.locator('.column-chooser__field', { hasText: 'process.command_line' })).toBeVisible()
  await expect(page.locator('.column-chooser__field', { hasText: 'file.path' })).toHaveCount(0)
  await capture(page, '08a-column-chooser-searching-process')
  for (const field of ['process.command_line', 'api.arguments', 'file.path', 'destination.domain']) {
    await page.getByRole('textbox', { name: 'Find a field' }).fill(field)
    await page.locator('.column-chooser__field', { hasText: field }).first().click()
  }
  await page.getByRole('textbox', { name: 'Find a field' }).fill('')
  await capture(page, '08b-column-chooser-four-chosen')
  await page.keyboard.press('Escape')
  await expect(page.locator('[role="columnheader"]', { hasText: 'PROCESS.COMMAND_LINE' })).toBeVisible()
  await expect(page.locator('[data-event-id]').first().locator('[data-column="process.command_line"]')).not.toBeEmpty()
  expect(mock.searches.at(-1)?.columns).toEqual(['process.command_line', 'api.arguments', 'file.path', 'destination.domain'])
  await expect(page.locator('.event-table__count')).toHaveText('100 of 250 events')
  await expectNoVerticalScroll(page)
  await capture(page, '08c-extra-columns-command-line-and-api-arguments')
  await page.getByRole('grid', { name: 'Events' }).evaluate((element) => element.parentElement!.scrollTo(element.scrollWidth, 0))
  await capture(page, '08e-extra-columns-scrolled-right')
  await page.reload()
  await expect(page.locator('[role="columnheader"]', { hasText: 'API.ARGUMENTS' })).toBeVisible()
})

test('events-h2-column-limit-message', async ({ page }) => {
  await page.addInitScript((columns) => window.localStorage.setItem('tartarus.events.columns', JSON.stringify(columns)), TWELVE_COLUMNS)
  const mock = await openLoadedEvents(page)
  expect(mock.searches[0]!.columns).toEqual(TWELVE_COLUMNS)
  await page.getByRole('button', { name: /COLUMNS/ }).click()
  await expect(page.locator('.column-chooser__limit')).toBeVisible()
  await expect(page.locator('.column-chooser__field input:disabled').first()).toBeDisabled()
  await capture(page, '08d-column-chooser-at-the-limit-of-12')
})

test('events-h3-remembered-column-that-is-gone-is-dropped', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('tartarus.events.columns', JSON.stringify(['file.path', 'gone.field'])))
  const mock = await openLoadedEvents(page)
  expect(mock.searches).toHaveLength(1)
  expect(mock.searches[0]!.columns).toEqual(['file.path'])
})

test('events-i-drawer-api-event', async ({ page }) => {
  await openDrawer(page, special.api)
  await expect(page.locator('.field-row').first()).toBeVisible()
  await expectContainedHorizontally(page, '.event-detail')
  await capture(page, '09-drawer-api-event')
  await page.locator('.event-detail__raw-toggle').click()
  await expect(page.locator('.event-detail__raw')).toBeVisible()
  await capture(page, '09b-drawer-api-event-raw-json-open')
})

test('events-j-drawer-alert-related-events', async ({ page }) => {
  await openDrawer(page, special.alert)
  await expect(page.getByText('REFERENCED BY')).toBeVisible()
  await page.locator('.event-detail__body').evaluate((element) => element.scrollTo(0, element.scrollHeight))
  await capture(page, '10-drawer-alert-references-and-referenced-by')
})

test('events-j2-drawer-alert-with-a-cut-list', async ({ page }) => {
  await openDrawer(page, special.bigAlert)
  await expect(page.getByText('showing 12 of 120')).toBeVisible()
  await page.locator('.event-detail__body').evaluate((element) => element.scrollTo(0, element.scrollHeight))
  await capture(page, '10b-drawer-alert-showing-12-of-120')
})

test('events-j3-related-event-opens-its-own-drawer', async ({ page }) => {
  await openDrawer(page, special.alert)
  await page.locator('.related-event').first().click()
  await expect(page.locator('.event-detail__title')).toContainText('benign.exe called')
  await expect(page).toHaveURL(/e=/)
  await expect(page).not.toHaveURL(new RegExp(special.alert))
})

test('events-k-drawer-long-command-line-and-path', async ({ page }) => {
  await openDrawer(page, special.longProcess)
  await page.locator('.field-row__value', { hasText: 'EncodedCommand' }).last().scrollIntoViewIfNeeded()
  await expectContainedHorizontally(page, '.event-detail__body')
  await capture(page, '11-drawer-very-long-command-line')
  await page.goto(`${EVENTS_URL}?e=${special.longFile}`)
  await expect(page.locator('.event-detail__title')).toContainText('loader_stage_two.exe')
  await page.locator('.field-row__value', { hasText: 'loader_stage_two.exe' }).last().scrollIntoViewIfNeeded()
  await expectContainedHorizontally(page, '.event-detail__body')
  await capture(page, '11b-drawer-very-long-file-path')
})

test('events-l-drawer-loading', async ({ page }) => {
  await openEvents(page, `e=${special.api}`, { detailDelayMs: HOLD_MS })
  await expect(page.locator('.event-detail__skeleton')).toBeVisible()
  await capture(page, '12-drawer-loading')
})

test('events-l2-drawer-event-gone', async ({ page }) => {
  await openLoadedEvents(page, 'e=deadbeefdeadbeefdeadbeef')
  await expect(page.getByText('event not found')).toBeVisible()
  await capture(page, '12b-drawer-event-not-found-404')
})

test('events-l3-drawer-error-with-retry', async ({ page }) => {
  await openLoadedEvents(page, `e=${special.api}`, {
    detailFailures: { [special.api]: { status: 502, code: 'search_failed', message: 'search failed' } },
  })
  await expect(page.getByText('failed to load: search failed')).toBeVisible()
  await capture(page, '12c-drawer-error-with-retry')
})

test('events-m-sorted-newest-first', async ({ page }) => {
  await openLoadedEvents(page)
  const firstOldest = await page.locator('[data-column="time"]').first().innerText()
  await page.getByRole('button', { name: /^TIME/ }).click()
  await expect(page.locator('[role="columnheader"]').first()).toHaveAttribute('aria-sort', 'descending')
  await expect(page.locator('[data-column="time"]').first()).not.toHaveText(firstOldest)
  await expectNoVerticalScroll(page)
  await capture(page, '13-sorted-newest-first')
})

test('events-n-scrolled-with-loading-more-footer', async ({ page }) => {
  const mock = await openLoadedEvents(page, '', { nextPageDelayMs: HOLD_MS })
  await page.locator('.event-table__list').evaluate((element) => element.scrollTo(0, element.scrollHeight))
  await expect(page.locator('.event-table__footer')).toContainText('loading more events')
  expect(mock.searches.filter((search) => search.search_after)).toHaveLength(1)
  await page.locator('.event-table__list').evaluate((element) => element.scrollTo(0, element.scrollHeight))
  await expect(page.locator('.event-table__footer')).toBeInViewport()
  await capture(page, '14-scrolled-to-the-end-loading-more')
})

test('events-n2-next-page-arrives-and-appends', async ({ page }) => {
  await openLoadedEvents(page)
  await page.locator('.event-table__list').evaluate((element) => element.scrollTo(0, element.scrollHeight))
  await expect(page.locator('.event-table__count')).toHaveText('200 of 250 events')
  await page.locator('.event-table__list').evaluate((element) => element.scrollTo(0, element.scrollHeight))
  await expect(page.locator('.event-table__count')).toHaveText('250 of 250 events')
  await capture(page, '14b-all-pages-loaded-at-the-end')
})

test('events-o-narrow-window-with-drawer', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 720 })
  await openDrawer(page, special.alert)
  await expectNoHorizontalOverflow(page)
  await capture(page, '15-narrow-800-with-drawer-open')
})

test('events-o2-narrow-window-table', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 720 })
  await openLoadedEvents(page)
  await expectNoHorizontalOverflow(page)
  await capture(page, '15b-narrow-800-table')
})

test('events-p-row-selected-by-keyboard', async ({ page }) => {
  await openLoadedEvents(page)
  await page.getByRole('grid', { name: 'Events' }).focus()
  for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowDown')
  await expect(page.locator('.event-row.is-selected')).toHaveAttribute('data-event-id', sampleEvents()[2]!.id)
  await expect(page.locator('.event-detail')).toHaveCount(0)
  await capture(page, '16-third-row-selected-by-keyboard')
  await page.keyboard.press('Enter')
  await expect(page.locator('.event-detail')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`e=${sampleEvents()[2]!.id}`))
})

test('events-q-drawer-steps-through-the-list-and-back-closes-it', async ({ page }) => {
  await openLoadedEvents(page)
  await page.locator('[data-event-id]').nth(1).click()
  await expect(page.locator('.event-detail')).toBeVisible()
  await expect(page.locator('[aria-label="Previous event"]')).toBeEnabled()
  await expect(page.locator('.event-detail')).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(page).toHaveURL(new RegExp(`e=${sampleEvents()[2]!.id}`))
  await expect(page.locator('.event-row.is-selected')).toHaveAttribute('data-event-id', sampleEvents()[2]!.id)
  await page.keyboard.press('Escape')
  await expect(page.locator('.event-detail')).toHaveCount(0)
  await expect(page).not.toHaveURL(/e=/)
  await page.goBack()
  await expect(page.locator('.event-detail')).toBeVisible()
})

test('events-r-filter-from-the-drawer-narrows-the-table', async ({ page }) => {
  await openDrawer(page, special.api)
  await page.getByRole('button', { name: 'Filter on api.name: NtWriteVirtualMemory' }).click()
  await expect(page.locator('.filter-chip')).toHaveCount(1)
  await expect(page).toHaveURL(/f=api\.name/)
})
