import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'

// The Events and Timeline halves of the submit flow, run on its finished analysis. Every count the
// page shows is compared with the same question asked of the real API, so a table that filters
// wrongly fails here and not only in a unit test with a stubbed store.

interface Chip {
  field: string
  value: string
  negate?: boolean
}
interface Filter {
  query?: string
  filters?: Chip[]
  time_range?: { from?: string; to?: string }
}

const COUNT_TIMEOUT = 15_000
const LANE_FIELD = 'tartarus.lane'
const PROCESS_FIELD = 'process.name'
const ACTION_FIELD = 'event.action'

const openTab = (page: Page, label: string) => page.getByRole('tab', { name: label, exact: true }).click()
const queryBar = (page: Page) => page.getByRole('combobox', { name: 'Query' })
const tableRows = (page: Page) => page.locator('.event-row')
const drawer = (page: Page) => page.getByRole('dialog', { name: 'Event detail' })

async function apiTotal(request: APIRequestContext, analysisId: string, filter: Filter): Promise<number> {
  const response = await request.post(`/api/analyses/${analysisId}/events/search`, { data: { ...filter, size: 1 } })
  expect(response.ok(), `POST events/search ${JSON.stringify(filter)} answered ${response.status()}`).toBe(true)
  return (await response.json()).total
}

async function footerTotal(page: Page): Promise<number> {
  const text = (await page.locator('.event-table__count').textContent({ timeout: 1000 }).catch(() => null)) ?? ''
  const match = /of ([\d,]+) events?/.exec(text)
  return match ? Number(match[1]!.replaceAll(',', '')) : Number.NaN
}

/** The footer count must reach what the API says for `filter`; both are read until they agree or time runs out. */
async function expectCountOf(page: Page, request: APIRequestContext, analysisId: string, filter: Filter, what: string): Promise<number> {
  const expected = await apiTotal(request, analysisId, filter)
  await expect
    .poll(() => footerTotal(page), { message: `the table footer for ${what} must equal the API's total ${expected} for ${JSON.stringify(filter)}`, timeout: COUNT_TIMEOUT })
    .toBe(expected)
  return expected
}

async function expectEveryVisibleRowIsInLane(page: Page, lane: string): Promise<void> {
  const lanes = await page.locator('.event-row [data-column="lane"]').evaluateAll((cells) => cells.map((cell) => cell.getAttribute('title')))
  expect(lanes.length, 'the filtered table must list rows').toBeGreaterThan(0)
  expect(new Set(lanes), `every visible row must be of the ${lane} lane`).toEqual(new Set([lane.toUpperCase()]))
}

function facetGroup(page: Page, field: string): Locator {
  return page.locator('.facet-group', { has: page.locator(`h4[title="${field}"]`) })
}

async function applyQuery(page: Page, text: string): Promise<void> {
  const bar = queryBar(page)
  await bar.fill(text)
  await bar.press('Enter')
}

const chipLocator = (page: Page, text: string) => page.locator('.filter-chip', { hasText: text })

async function removeChip(page: Page, text: string): Promise<void> {
  await page.getByLabel(`Remove filter ${text}`).click()
  await expect(chipLocator(page, text)).toHaveCount(0)
}

async function expectUrlParam(page: Page, name: string, expected: string | null): Promise<void> {
  await expect.poll(() => new URL(page.url()).searchParams.get(name), { message: `the URL parameter ${name} must be ${expected}` }).toBe(expected)
}

async function expectEventsList(page: Page, request: APIRequestContext, analysisId: string): Promise<number> {
  await openTab(page, 'EVENTS')
  await expect(tableRows(page).first(), 'the Events table must show rows').toBeVisible()
  const total = await expectCountOf(page, request, analysisId, {}, 'the unfiltered table')
  const lanes = facetGroup(page, LANE_FIELD).locator('.facet-value')
  await expect(lanes.first(), 'the facet panel must list the lanes').toBeVisible()
  expect(await lanes.count(), 'the lane facet lists more than one lane').toBeGreaterThan(1)
  return total
}

async function expectQueryNarrows(page: Page, request: APIRequestContext, analysisId: string): Promise<number> {
  await applyQuery(page, 'lane:process')
  await expectUrlParam(page, 'q', 'lane:process')
  const narrowed = await expectCountOf(page, request, analysisId, { query: 'lane:process' }, 'the query lane:process')
  await expectEveryVisibleRowIsInLane(page, 'process')
  return narrowed
}

/** Clicks the first value of a facet (alt-click filters it out); returns it with the count the facet showed. */
async function pickFirstValue(page: Page, field: string, modifiers: 'Alt'[] = []): Promise<{ name: string; count: number }> {
  const first = facetGroup(page, field).locator('.facet-value').first()
  await expect(first, `the ${field} facet must list a value`).toBeVisible()
  const name = (await first.locator('.facet-value__name').textContent())!.trim()
  const count = Number((await first.locator('.facet-value__count').textContent())!.replaceAll(',', ''))
  await first.locator('.facet-value__pick').click({ modifiers })
  return { name, count }
}

const pickFirstProcessValue = (page: Page) => pickFirstValue(page, PROCESS_FIELD)

async function expectChipsFilter(page: Page, request: APIRequestContext, analysisId: string): Promise<void> {
  const { name, count } = await pickFirstProcessValue(page)
  const include: Chip = { field: PROCESS_FIELD, value: name }
  const chipText = `${PROCESS_FIELD}: ${name}`
  await expect(chipLocator(page, chipText), `clicking ${name} must add a chip`).toBeVisible()
  const included = await expectCountOf(page, request, analysisId, { query: 'lane:process', filters: [include] }, `the chip ${chipText}`)
  expect(included, `the facet showed ${count} events for ${name}`).toBe(count)

  await page.getByRole('button', { name: `Filter out ${PROCESS_FIELD}: ${name}` }).click()
  await expect(chipLocator(page, chipText), 'the minus button must negate the chip').toHaveClass(/is-negated/)
  await expectCountOf(page, request, analysisId, { query: 'lane:process', filters: [{ ...include, negate: true }] }, `the negated chip ${chipText}`)

  const action = await pickFirstValue(page, ACTION_FIELD, ['Alt'])
  const actionChipText = `${ACTION_FIELD}: ${action.name}`
  await expect(chipLocator(page, actionChipText), 'alt-click must add a negated chip').toHaveClass(/is-negated/)
  await expectCountOf(
    page,
    request,
    analysisId,
    { query: 'lane:process', filters: [{ ...include, negate: true }, { field: ACTION_FIELD, value: action.name, negate: true }] },
    'both negated chips',
  )

  await removeChip(page, actionChipText)
  await removeChip(page, chipText)
  await expectCountOf(page, request, analysisId, { query: 'lane:process' }, 'the query alone after the chips are removed')
}

async function expectStateSurvivesReload(page: Page, request: APIRequestContext, analysisId: string): Promise<void> {
  const { name } = await pickFirstProcessValue(page)
  const chipText = `${PROCESS_FIELD}: ${name}`
  await expect(chipLocator(page, chipText)).toBeVisible()
  const filter = { query: 'lane:process', filters: [{ field: PROCESS_FIELD, value: name }] }
  await expectCountOf(page, request, analysisId, filter, 'the query and chip before the reload')

  await page.reload()
  await expect(queryBar(page), 'the query bar must come back with the query from the URL').toHaveValue('lane:process')
  await expect(chipLocator(page, chipText), 'the chip must come back from the URL').toBeVisible()
  await expectCountOf(page, request, analysisId, filter, 'the restored query and chip')

  await removeChip(page, chipText)
}

async function expectClearReturnsToTheFullList(page: Page, request: APIRequestContext, analysisId: string, total: number): Promise<void> {
  await page.getByRole('button', { name: 'Clear query' }).click()
  await expect(queryBar(page)).toHaveValue('')
  await expectUrlParam(page, 'q', null)
  await expectCountOf(page, request, analysisId, {}, 'the cleared query')
  expect(await footerTotal(page), 'clearing must return the table to every event').toBe(total)
}

async function expectDrawerOpensAndMoves(page: Page): Promise<void> {
  const rows = tableRows(page)
  const first = rows.first()
  const firstId = (await first.getAttribute('data-event-id'))!
  const secondId = (await rows.nth(1).getAttribute('data-event-id'))!
  const firstTitle = (await first.locator('[data-column="summary"]').textContent())?.trim() || (await first.locator('[data-column="action"]').textContent())?.trim()
  await first.click()

  await expect(drawer(page), 'clicking a row must open the detail drawer').toBeVisible()
  await expectUrlParam(page, 'e', firstId)
  await expect(drawer(page).locator('.event-detail__summary'), "the drawer's header must be the row's summary").toHaveText(firstTitle!)

  await drawer(page).getByRole('button', { name: /RAW JSON/ }).click()
  const raw = await drawer(page).locator('.event-detail__raw').textContent()
  expect(JSON.parse(raw!).event.id, 'the raw JSON must be the stored document of the opened event').toBe(firstId)

  await drawer(page).locator('.event-detail').focus()
  await page.keyboard.press('ArrowDown')
  await expectUrlParam(page, 'e', secondId)

  await page.keyboard.press('Escape')
  await expect(drawer(page), 'Escape must close the drawer').toBeHidden()
  await expectUrlParam(page, 'e', null)
}

async function expectBadQueryIsFlaggedAndNotApplied(page: Page, total: number): Promise<void> {
  const bar = queryBar(page)
  await bar.fill('procss:x')
  await expect(page.locator('.query-bar__error'), 'the bad field must be underlined').toHaveText('procss')
  await expect(page.locator('.query-bar__message'), 'the message must name the unknown field').toContainText("unknown field 'procss'")
  await expect(bar).toHaveAttribute('aria-invalid', 'true')
  await bar.press('Enter')
  await expectUrlParam(page, 'q', null)
  expect(await footerTotal(page), 'a query that does not compile must leave the table as it was').toBe(total)
  await page.getByRole('button', { name: 'Clear query' }).click()
  await expect(page.locator('.query-bar__message')).toHaveCount(0)
}

/** Returns the number of events of the whole analysis, which the Timeline checks need. */
export async function expectEventsTab(page: Page, request: APIRequestContext, analysisId: string): Promise<number> {
  const total = await expectEventsList(page, request, analysisId)
  await expectQueryNarrows(page, request, analysisId)
  await expectChipsFilter(page, request, analysisId)
  await expectStateSurvivesReload(page, request, analysisId)
  await expectClearReturnsToTheFullList(page, request, analysisId, total)
  await expectDrawerOpensAndMoves(page)
  await expectBadQueryIsFlaggedAndNotApplied(page, total)
  return total
}

interface Geometry {
  gutter: number
  plotWidth: number
  axisY: number
  viewStart: number
  viewEnd: number
}

const timelineRoot = (page: Page) => page.locator('.timeline')

async function geometryOf(page: Page): Promise<Geometry> {
  return JSON.parse((await timelineRoot(page).getAttribute('data-geometry'))!)
}

async function expectCanvasDraws(page: Page): Promise<void> {
  await openTab(page, 'TIMELINE')
  await expect(timelineRoot(page), 'the timeline canvas must be on the page').toBeVisible()
  await expect
    .poll(
      async () => {
        const root = timelineRoot(page)
        return Number(await root.getAttribute('data-marks')) + Number(await root.getAttribute('data-bars'))
      },
      { message: 'the timeline must draw marks or count bars', timeout: COUNT_TIMEOUT },
    )
    .toBeGreaterThan(0)
}

/** Drags across the axis from `from` to `to`, fractions of the plot's width. */
async function brushAxis(page: Page, from: number, to: number): Promise<void> {
  const canvas = page.locator('.timeline__canvas')
  const box = (await canvas.boundingBox())!
  const { gutter, plotWidth, axisY } = await geometryOf(page)
  const y = box.y + axisY
  await page.mouse.move(box.x + gutter + plotWidth * from, y)
  await page.mouse.down()
  await page.mouse.move(box.x + gutter + plotWidth * ((from + to) / 2), y, { steps: 5 })
  await page.mouse.move(box.x + gutter + plotWidth * to, y, { steps: 5 })
  await page.mouse.up()
}

function timeRangeOfUrl(page: Page): { from: string; to: string } | null {
  const raw = new URL(page.url()).searchParams.get('t')
  const [from, to] = raw?.split('..') ?? []
  return from && to ? { from, to } : null
}

async function expectBrushFiltersTheTable(page: Page, request: APIRequestContext, analysisId: string, total: number): Promise<void> {
  await brushAxis(page, 0.3, 0.55)
  await expect.poll(() => timeRangeOfUrl(page), { message: 'a brush must put a time range in the URL (t=)' }).not.toBeNull()
  await expect(page.locator('.filter-chip', { hasText: 'time:' }), 'a brush must show a time chip').toBeVisible()
  const range = timeRangeOfUrl(page)!
  const inRange = await expectCountOf(page, request, analysisId, { time_range: range }, `the brushed range ${range.from}..${range.to}`)
  expect(inRange, 'the brushed range must narrow the table').toBeLessThan(total)
  expect(inRange).toBeGreaterThan(0)
}

async function expectDoubleClickResetsTheView(page: Page): Promise<void> {
  const fitted = await geometryOf(page)
  await page.locator('label[for="timeline-zoom-10s"]').click()
  await expect
    .poll(async () => (await geometryOf(page)).viewEnd - (await geometryOf(page)).viewStart, { message: 'zooming to 10 s must narrow the view' })
    .toBeLessThan(fitted.viewEnd - fitted.viewStart)
  const canvas = page.locator('.timeline__canvas')
  const box = (await canvas.boundingBox())!
  await page.mouse.dblclick(box.x + fitted.gutter + fitted.plotWidth / 2, box.y + fitted.axisY)
  await expect
    .poll(async () => geometryOf(page), { message: 'a double-click must fit the whole run again' })
    .toMatchObject({ viewStart: fitted.viewStart, viewEnd: fitted.viewEnd })
}

export async function expectTimelineTab(page: Page, request: APIRequestContext, analysisId: string, total: number): Promise<void> {
  await expectCanvasDraws(page)
  await expectBrushFiltersTheTable(page, request, analysisId, total)
  await expectDoubleClickResetsTheView(page)
}
