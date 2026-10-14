import type { Locator, Page } from '@playwright/test'
import type { Event } from '../../src/api/types.gen'
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
  sampleEvents,
  screenshotPath,
  test,
  waitForTransitions,
  type EventsMock,
  type EventsMockOptions,
} from './fixtures'
import { closeEvents, denseEvents } from './timeline-data'

const ID = 45
const TIMELINE_URL = `/analyses/${ID}/timeline`
const HOLD_MS = 120_000
const TABLE_PAGE_SIZE = 100
const SAMPLE = sampleEvents()
const TIMEOUT = { status: 504, code: 'search_timeout', message: 'the search took too long (10 s), narrow the query and try again' }

interface Geometry {
  gutter: number
  plotWidth: number
  detectionY: number
  axisY: number
  lanes: Record<string, number>
  viewStart: number
  viewEnd: number
}

const timeline = (page: Page): Locator => page.locator('.timeline')

async function openTimeline(page: Page, search = '', options: EventsMockOptions = {}): Promise<EventsMock> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockQuery(page)
  const mock = await mockEvents(page, options)
  await page.goto(`${TIMELINE_URL}${search ? `?${search}` : ''}`)
  await expect(page.getByRole('combobox', { name: 'Query' })).toBeVisible()
  return mock
}

async function openDrawn(page: Page, search = '', options: EventsMockOptions = {}, source: 'events' | 'buckets' = 'events'): Promise<EventsMock> {
  const mock = await openTimeline(page, search, options)
  await expect(timeline(page)).toHaveAttribute('data-source', source)
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await waitForTransitions(page)
  return mock
}

async function capture(page: Page, name: string): Promise<void> {
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(`timeline/${name}`) })
}

async function geometry(page: Page): Promise<Geometry> {
  return JSON.parse((await timeline(page).getAttribute('data-geometry'))!) as Geometry
}

/** Where on the page a time and a lane (or the axis, or the detection track) are, read from what the canvas says of itself. */
async function pointAt(page: Page, time: number, row: string): Promise<{ x: number; y: number }> {
  const geo = await geometry(page)
  const box = (await page.locator('.timeline__canvas').boundingBox())!
  const y = row === 'axis' ? geo.axisY : row === 'detection' ? geo.detectionY : geo.lanes[row]!
  return { x: box.x + geo.gutter + ((time - geo.viewStart) / (geo.viewEnd - geo.viewStart)) * geo.plotWidth, y: box.y + y }
}

const timeOf = (event: Event): number => Date.parse(event.time)
const firstOfLane = (lane: string, events: Event[] = SAMPLE): Event => events.find((event) => event.lane === lane && event.kind === 'event')!
const ALERT = SAMPLE.find((event) => event.kind === 'alert')!

async function visibleSpanMs(page: Page): Promise<number> {
  const geo = await geometry(page)
  return geo.viewEnd - geo.viewStart
}

async function dragOnAxis(page: Page, fromTime: number, toTime: number, release = true): Promise<void> {
  const from = await pointAt(page, fromTime, 'axis')
  const to = await pointAt(page, toTime, 'axis')
  await page.mouse.move(from.x, from.y)
  await page.mouse.down()
  await page.mouse.move((from.x + to.x) / 2, to.y, { steps: 4 })
  await page.mouse.move(to.x, to.y, { steps: 4 })
  if (release) await page.mouse.up()
}

async function expectFitsOneScreen(page: Page): Promise<void> {
  await expectNoVerticalScroll(page)
  await expectNoHorizontalOverflow(page)
}

test('timeline-a-fit-view-all-lanes-and-detections', async ({ page }) => {
  await openDrawn(page)
  await expect(timeline(page)).toHaveAttribute('data-detections', String(SAMPLE.filter((event) => event.kind === 'alert').length))
  expect(Number(await timeline(page).getAttribute('data-marks'))).toBeGreaterThan(30)
  await expect(page.locator('.timeline__gutter-label')).toHaveText(['DETECTIONS', 'PROCESS', 'FILE', 'REGISTRY', 'NETWORK', 'MEMORY', 'API', 'UTC'])
  await expect(page.locator('.event-table__count')).toHaveText('100 of 250 events')
  await expectFitsOneScreen(page)
  await capture(page, '01-fit-view-all-lanes-1280x720')
})

test('timeline-b-dense-analysis-count-bars', async ({ page }) => {
  const mock = await openDrawn(page, '', { events: denseEvents(SAMPLE) }, 'buckets')
  expect(Number(await timeline(page).getAttribute('data-bars'))).toBeGreaterThan(100)
  expect(mock.searches.every((body) => body.size !== 500), 'no individual events are asked for above the threshold').toBe(true)
  await expectFitsOneScreen(page)
  await capture(page, '02-dense-analysis-count-bars-1280x720')
})

test('timeline-c-zoomed-to-10s-individual-marks', async ({ page }) => {
  const mock = await openDrawn(page, '', { events: denseEvents(SAMPLE) }, 'buckets')
  await page.locator('label[for="timeline-zoom-10s"]').click()
  await expect(timeline(page)).toHaveAttribute('data-source', 'events')
  expect(await visibleSpanMs(page)).toBe(10_000)
  await expect(page.locator('.timeline-tab__zoom input[value="10s"]')).toBeChecked()
  await expect(page.locator('.event-table__count')).toHaveText(/^\d+ of (\d{1,3}(,\d{3})*) events$/)
  const restricted = mock.searches.at(-1)!
  expect(restricted.time_range?.from, 'the table below follows the visible range').toBeDefined()
  await expectFitsOneScreen(page)
  await capture(page, '03-zoomed-10s-individual-marks')
})

test('timeline-d-tooltip-on-a-mark', async ({ page }) => {
  await openDrawn(page)
  const file = firstOfLane('file')
  const { x, y } = await pointAt(page, timeOf(file), 'file')
  await page.mouse.move(x, y)
  await expect(page.locator('.timeline__tooltip')).toContainText(file.summary!)
  await capture(page, '04a-tooltip-on-a-mark')
})

test('timeline-d-tooltip-on-a-bar', async ({ page }) => {
  await openDrawn(page, '', { events: denseEvents(SAMPLE) }, 'buckets')
  const geo = await geometry(page)
  const middle = geo.viewStart + (geo.viewEnd - geo.viewStart) / 2
  const { x, y } = await pointAt(page, middle, 'api')
  await page.mouse.move(x, y)
  await expect(page.locator('.timeline__tooltip')).toContainText('API events')
  await capture(page, '04b-tooltip-on-a-bar')
})

test('timeline-d-tooltip-on-a-detection', async ({ page }) => {
  await openDrawn(page)
  const { x, y } = await pointAt(page, timeOf(ALERT), 'detection')
  await page.mouse.move(x, y)
  await expect(page.locator('.timeline__tooltip')).toContainText(ALERT.rule_name!)
  await capture(page, '04c-tooltip-on-a-detection')
})

test('timeline-e-brush-in-progress-and-released', async ({ page }) => {
  const mock = await openDrawn(page)
  const from = timeOf(SAMPLE[0]!) + 12_000
  const to = timeOf(SAMPLE[0]!) + 26_000
  await dragOnAxis(page, from, to, false)
  await capture(page, '05a-brush-in-progress')
  await page.mouse.up()
  await expect(page.locator('.filter-chip', { hasText: 'time:' })).toBeVisible()
  await expect(page.locator('.event-table__count')).toHaveText(/^\d+ of \d+ events$/)
  expect(mock.searches.at(-1)!.time_range, 'the chip restricts the table').toBeDefined()
  await expectFitsOneScreen(page)
  await capture(page, '05b-brush-released-chip-and-restricted-table')
})

test('timeline-f-existing-chip-band-with-handles', async ({ page }) => {
  const start = timeOf(SAMPLE[0]!)
  const range = `${new Date(start + 10_000).toISOString()}..${new Date(start + 30_000).toISOString()}`
  await openDrawn(page, `t=${encodeURIComponent(range)}`)
  await expect(page.locator('.filter-chip', { hasText: 'time:' })).toBeVisible()
  await expectFitsOneScreen(page)
  await capture(page, '06a-chip-band-with-handles')
  const end = await pointAt(page, start + 30_000, 'axis')
  await page.mouse.move(end.x, end.y)
  await page.mouse.down()
  await page.mouse.move(end.x + 60, end.y, { steps: 6 })
  await capture(page, '06b-dragging-a-handle')
  await page.mouse.up()
  await expect(page.locator('.filter-chip', { hasText: 'time:' })).toBeVisible()
})

test('timeline-g-selected-event-highlighted', async ({ page }) => {
  const selected = SAMPLE.filter((event) => event.lane === 'file' && event.kind === 'event')[3]!
  await openDrawn(page, `e=${encodeURIComponent(selected.id)}`)
  await expect(page.locator('.event-detail')).toBeVisible()
  await capture(page, '07a-selected-event-drawer-open')
  await page.keyboard.press('Escape')
  await expect(page.locator('.event-detail')).toHaveCount(0)
  await capture(page, '07b-selected-event-highlight-drawer-closed')
})

test('timeline-g2-click-a-mark-opens-the-drawer', async ({ page }) => {
  await openDrawn(page)
  const file = firstOfLane('file')
  const { x, y } = await pointAt(page, timeOf(file), 'file')
  await page.mouse.click(x, y)
  await expect(page.locator('.event-detail')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`e=${file.id}`))
})

test('timeline-h-loading', async ({ page }) => {
  await openTimeline(page, '', { histogramDelayMs: HOLD_MS })
  await expect(page.locator('.timeline-tab__canvas .loader')).toBeVisible()
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await expectFitsOneScreen(page)
  await capture(page, '08a-loading')
})

test('timeline-h-empty-analysis', async ({ page }) => {
  await openTimeline(page, '', { events: [] })
  await expect(page.getByText('> no events in this analysis')).toBeVisible()
  await expectFitsOneScreen(page)
  await capture(page, '08b-empty-analysis')
})

test('timeline-h-error-with-retry', async ({ page }) => {
  await openTimeline(page, '', { histogramFailure: TIMEOUT })
  await expect(page.getByText('failed to load: the search took too long')).toBeVisible()
  await expect(page.locator('[data-event-id]').first(), 'the table does not depend on the histogram').toBeVisible()
  await expect(page.locator('.timeline-tab__canvas').getByRole('button', { name: '[RETRY]' })).toBeVisible()
  await expectFitsOneScreen(page)
  await capture(page, '08c-histogram-error-with-retry')
})

test('timeline-h-table-error-canvas-unaffected', async ({ page }) => {
  await openTimeline(page, '', { searchFailure: TIMEOUT, searchFailureWhen: (body) => (body.size ?? 0) <= TABLE_PAGE_SIZE })
  await expect(page.locator('.event-table').getByText('failed to load: the search took too long')).toBeVisible()
  await expectFitsOneScreen(page)
  await capture(page, '08d-table-error-canvas-unaffected')
})

test('timeline-i-process-filter-thins-the-lanes', async ({ page }) => {
  await openDrawn(page)
  const all = Number(await timeline(page).getAttribute('data-marks'))
  await page.goto(`${TIMELINE_URL}?f=process.name:cmd.exe`)
  await expect(page.locator('.filter-chip')).toHaveCount(1)
  await expect.poll(async () => Number(await timeline(page).getAttribute('data-marks'))).toBeLessThan(all)
  await expect(page.locator('[data-event-id]').first()).toBeVisible()
  await expectFitsOneScreen(page)
  await capture(page, '09a-filter-process-chip-thinned-lanes')
})

test('timeline-i-lane-query-leaves-one-lane', async ({ page }) => {
  await openDrawn(page, `q=${encodeURIComponent('lane:network')}`)
  await expect.poll(async () => Number(await timeline(page).getAttribute('data-marks'))).toBeLessThan(40)
  await expectFitsOneScreen(page)
  await capture(page, '09b-filter-lane-query-one-lane')
})

test('timeline-j-narrow-window', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 720 })
  await openDrawn(page)
  await expectNoHorizontalOverflow(page)
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath('timeline/10-narrow-800x720'), fullPage: true })
})

test('timeline-k-millisecond-zoom-with-very-close-events', async ({ page }) => {
  const events = closeEvents(SAMPLE)
  await openDrawn(page, '', { events })
  const centre = Date.parse('2026-10-13T15:40:10.005Z')
  const { x, y } = await pointAt(page, centre, 'registry')
  await page.mouse.move(x, y)
  for (let step = 0; step < 16 && (await visibleSpanMs(page)) > 10; step++) {
    await page.mouse.wheel(0, -500)
    await page.waitForTimeout(40)
  }
  await expect.poll(() => visibleSpanMs(page)).toBeLessThanOrEqual(10)
  await expect.poll(async () => Number(await timeline(page).getAttribute('data-marks'))).toBeGreaterThan(5)
  await page.mouse.move(x, y + 1)
  await expectFitsOneScreen(page)
  await capture(page, '11-zoom-10ms-very-close-events')
  const stack = await pointAt(page, Date.parse('2026-10-13T15:40:10.003Z'), 'api')
  await page.mouse.move(stack.x, stack.y)
  await expect(page.locator('.timeline__tooltip')).toBeVisible()
  await capture(page, '11b-zoom-10ms-tooltip-on-a-stack-at-one-instant')
})

test('timeline-l-wide-window', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await openDrawn(page)
  await expectFitsOneScreen(page)
  await capture(page, '12-wide-1920x1080')
})

test('timeline-m-wheel-zooms-around-the-cursor-and-a-drag-pans', async ({ page }) => {
  await openDrawn(page)
  const before = await geometry(page)
  const middle = before.viewStart + (before.viewEnd - before.viewStart) * 0.5
  const { x, y } = await pointAt(page, middle, 'registry')
  await page.mouse.move(x, y)
  await page.mouse.wheel(0, -500)
  await expect.poll(() => visibleSpanMs(page)).toBeLessThan(before.viewEnd - before.viewStart)
  const zoomed = await geometry(page)
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + 150, y, { steps: 5 })
  await page.mouse.up()
  await expect.poll(async () => (await geometry(page)).viewStart).toBeLessThan(zoomed.viewStart)
  await page.mouse.dblclick(x, y)
  await expect.poll(async () => (await geometry(page)).viewStart).toBe(before.viewStart)
})

test('timeline-n-keyboard', async ({ page }) => {
  await openDrawn(page)
  const fit = await geometry(page)
  await page.locator('.timeline__canvas').focus()
  await page.keyboard.press('+')
  await expect.poll(() => visibleSpanMs(page)).toBeLessThan(fit.viewEnd - fit.viewStart)
  await page.keyboard.press('Home')
  await expect.poll(async () => (await geometry(page)).viewStart).toBe(fit.viewStart)
  await page.keyboard.press('0')
  await expect.poll(() => visibleSpanMs(page)).toBe(fit.viewEnd - fit.viewStart)
  await expect(page.locator('.timeline__canvas')).toBeFocused()
  await capture(page, '13-keyboard-focus-ring')
})
