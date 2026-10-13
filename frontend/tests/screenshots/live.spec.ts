import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import {
  GUEST_READY_SYSTEM,
  NARROW_AND_WIDE_WIDTHS,
  expect,
  expectNoHorizontalOverflow,
  expectNoVerticalScroll,
  makeAnalysis,
  makeDetectedAnalysis,
  mockAnalyses,
  mockEvolvingAnalysis,
  mockLiveSocket,
  mockShell,
  mockViews,
  screenshotPath,
  test,
  waitForTransitions,
  type LiveSocketMock,
} from './fixtures'
import {
  NON_API_EVENTS,
  PROCESSES,
  RUNNING_STATUS,
  SESSION_EVENTS,
  countsMessage,
  fillerEvents,
  type SessionProcess,
} from './live-session'

const ID = 45
const ROUTE = `/analyses/${ID}`

function runningAnalysis(overrides: Partial<AnalysisRead> = {}): AnalysisRead {
  return makeAnalysis({
    id: ID,
    status: 'running',
    filename: 'invoice_scan.exe',
    started_at: '2026-10-13T15:39:20Z',
    options: { route: 'inetsim', timeout: 180 },
    ...overrides,
  })
}

function finishedAnalysis(): AnalysisRead {
  return makeDetectedAnalysis({
    id: ID,
    filename: 'invoice_scan.exe',
    started_at: '2026-10-13T15:39:20Z',
    finished_at: '2026-10-13T15:42:31Z',
  })
}

interface OpenOptions {
  analysis?: AnalysisRead
  route?: string
  waitForSocket?: boolean
}

async function openLive(page: Page, options: OpenOptions = {}): Promise<LiveSocketMock> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [options.analysis ?? runningAnalysis()] })
  await mockViews(page)
  const live = await mockLiveSocket(page, ID)
  await page.goto(options.route ?? ROUTE)
  if (options.waitForSocket !== false) await live.connected()
  return live
}

function feedProcesses(live: LiveSocketMock, processes: SessionProcess[]): void {
  for (const { pid, ppid, name, executable, command_line, start, end } of processes) {
    const node = { pid, ppid, name, executable, command_line, start, end: null }
    live.send('process', { op: 'add', node })
    if (end !== null) live.send('process', { op: 'end', node: { ...node, end } })
  }
}

function stream(live: LiveSocketMock, processes = PROCESSES.length, events = NON_API_EVENTS): void {
  live.send('status', RUNNING_STATUS)
  feedProcesses(live, PROCESSES.slice(0, processes))
  live.sendEvents(events)
  live.send('counts', countsMessage(SESSION_EVENTS))
}

async function expectFollowingNewest(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.locator('.live-stream__list').evaluate((list) => list.scrollHeight - list.scrollTop - list.clientHeight),
    )
    .toBeLessThanOrEqual(2)
}

async function showApiCalls(page: Page): Promise<void> {
  await page.locator('.live-stream__api input').check()
}

async function expectPanelsInsideViewport(page: Page): Promise<void> {
  const { innerHeight } = await page.evaluate(() => ({ innerHeight: window.innerHeight }))
  for (const part of ['status', 'processes', 'stream']) {
    const box = (await page.locator(`[data-live="${part}"]`).boundingBox())!
    expect(box.y + box.height, `${part} reaches below the window`).toBeLessThanOrEqual(innerHeight)
  }
}

async function snapshot(page: Page, name: string): Promise<void> {
  // A pointer left over a button from the last click would paint its hover state into the picture.
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

test('live-default-tab-for-a-running-analysis', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  await expect(page.locator('.analysis-tabs [aria-selected="true"]')).toHaveText('LIVE')
  await expect(page.locator('.analysis-tabs button').first()).toHaveText('LIVE')
  await expect(page.locator('[data-tab="live"]')).toBeVisible()
})

test('live-streaming-early', async ({ page }) => {
  const live = await openLive(page)
  live.send('status', RUNNING_STATUS)
  feedProcesses(live, PROCESSES.slice(0, 2))
  live.sendEvents(NON_API_EVENTS.slice(0, 2))
  await expect(page.locator('.live-event')).toHaveCount(2)
  live.sendEvents(NON_API_EVENTS.slice(2, 6))
  await expect(page.locator('.live-process')).toHaveCount(2)
  await expect(page.locator('.live-event'), 'a second batch extends a list that is mostly empty').toHaveCount(6)
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-streaming-early')
})

for (const width of NARROW_AND_WIDE_WIDTHS) {
  test(`live-streaming-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1280 ? 720 : 900 })
    const live = await openLive(page)
    stream(live)
    await expect(page.locator('.live-process')).toHaveCount(PROCESSES.length)
    await expect(page.locator('.live-event').first()).toBeVisible()
    await expectFollowingNewest(page)
    await expectNoHorizontalOverflow(page)
    if (width === 1280) {
      await expectNoVerticalScroll(page)
      await expectPanelsInsideViewport(page)
      await expect(page.locator('[data-live="desktop"]')).toHaveCount(0)
    }
    await snapshot(page, width === 1280 ? 'live-streaming' : 'live-streaming-narrow-600')
  })
}

test('live-waiting-for-the-guest', async ({ page }) => {
  const live = await openLive(page, { analysis: runningAnalysis({ status: 'starting' }) })
  live.send('status', { status: 'starting', phase: 'live', elapsed_s: 3, remaining_s: 177 })
  await expect(page.locator('[data-live="processes"]')).toContainText('starting the guest...')
  await expect(page.locator('.live-stream__empty')).toContainText('starting the guest...')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-waiting-for-the-guest')
})

test('live-connected-no-events-yet', async ({ page }) => {
  const live = await openLive(page)
  live.send('status', RUNNING_STATUS)
  feedProcesses(live, PROCESSES.slice(0, 1))
  await expect(page.locator('.live-stream__empty')).toContainText('connected, no events yet')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-connected-no-events-yet')
})

test('live-queued', async ({ page }) => {
  const live = await openLive(page, { analysis: runningAnalysis({ status: 'queued', started_at: null, queue_position: 2 }) })
  live.send('status', { status: 'queued', phase: 'live', elapsed_s: null, remaining_s: null })
  await expect(page.locator('.live-stream__empty')).toContainText('queued, position 2')
  await expect(page.locator('[data-live="status"]')).toContainText('position 2 in the queue')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-queued')
})

test('live-show-api-calls', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  await expect(page.locator('.live-event')).not.toHaveCount(0)
  await showApiCalls(page)
  await expect.poll(() => live.subscriptions().at(-1)).toMatchObject({ include_api: true })
  live.sendEvents(SESSION_EVENTS)
  await expect(page.locator('.live-event__lane', { hasText: 'API' }).first()).toBeVisible()
  await expectFollowingNewest(page)
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-show-api-calls')
})

test('live-paused-with-backlog', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  await showApiCalls(page)
  await expect.poll(() => live.subscriptions().at(-1)).toMatchObject({ include_api: true })
  live.sendEvents(SESSION_EVENTS.slice(0, 150))
  await expect(page.locator('.live-event').first()).toBeVisible()
  await page.locator('.live-stream__pause').click()
  live.sendEvents(SESSION_EVENTS.slice(150))
  await expect(page.locator('.live-stream__pause')).toContainText('+')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-paused-with-backlog')
})

test('live-server-skipped-events', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  live.sendEvents(NON_API_EVENTS.slice(0, 3), 1530)
  await expect(page.locator('.live-stream__skipped')).toContainText('1,530 events skipped by the server, open table')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-server-skipped-events')
})

test('live-local-trim', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  await showApiCalls(page)
  await expect.poll(() => live.subscriptions().at(-1)).toMatchObject({ include_api: true })
  const filler = fillerEvents(5300)
  for (let from = 0; from < filler.length; from += 500) live.sendEvents(filler.slice(from, from + 500))
  await expect(page.locator('.live-stream__trimmed')).toContainText(/older events trimmed/)
  await expectFollowingNewest(page)
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-local-trim')
})

test('live-reconnecting', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  await page.locator('.live-stream__lane', { hasText: 'FILE' }).click()
  await expect.poll(() => live.subscriptions().at(-1)).toMatchObject({ lanes: ['file'] })
  live.close(1006)
  await expect(page.locator('[data-field="link"]')).toContainText('RECONNECTING')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-reconnecting')

  await live.connected(2)
  expect(live.subscriptions().at(-1), 'the filter is sent again on the new socket').toMatchObject({ lanes: ['file'] })
  live.send('status', RUNNING_STATUS)
  await expect(page.locator('[data-field="link"]')).toContainText('CONNECTED')
})

test('live-selected-process', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  await showApiCalls(page)
  await expect.poll(() => live.subscriptions().at(-1)).toMatchObject({ include_api: true })
  live.sendEvents(SESSION_EVENTS)
  await page.locator('.live-process', { hasText: 'powershell.exe' }).click()
  await expect.poll(() => live.subscriptions().at(-1)).toMatchObject({ pids: [5012] })
  await expect(page.locator('.live-process--selected')).toHaveCount(1)
  await expect
    .poll(async () => new Set(await page.locator('.live-event .process-chip').allTextContents()).size)
    .toBe(1)
  expect(await page.locator('.live-event .process-chip').first().textContent()).toBe('powershell.exe (5012)')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-selected-process')

  await page.locator('.live-process--selected').click()
  await expect(page.locator('.live-process--selected')).toHaveCount(0)
  await expect.poll(() => live.subscriptions().at(-1)).not.toHaveProperty('pids')
})

test('live-lane-filter', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  await page.locator('.live-stream__lane', { hasText: 'NETWORK' }).click()
  await page.locator('.live-stream__lane', { hasText: 'REGISTRY' }).click()
  await expect.poll(() => live.subscriptions().at(-1)).toMatchObject({ lanes: ['network', 'registry'] })
  await expect
    .poll(async () => [...new Set(await page.locator('.live-event__lane').allTextContents())].sort())
    .toEqual(['NETWORK', 'REGISTRY'])
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-lane-filter')
})

test('live-server-error-notices', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  live.send('error', { code: 'live_index_failed', message: 'OpenSearch rejected the bulk request: index_closed_exception' })
  live.send('error', { code: 'log_format', message: 'unknown message type 9 in logs/2476.bson' })
  await expect(page.locator('.live-tab__notices .live-notice')).toHaveCount(2)
  await expect(page.locator('.live-event').first()).toBeVisible()
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-server-error-notices')
})

test('live-unknown-to-the-stream', async ({ page }) => {
  const live = await openLive(page)
  live.close(4404)
  await expect(page.locator('.live-tab__notices')).toContainText('the live stream does not know this analysis')
  await expect(page.locator('[data-field="link"]')).toContainText('CLOSED')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-unknown-to-the-stream')
})

test('live-many-processes-scroll-inside-their-panel', async ({ page }) => {
  const live = await openLive(page)
  stream(live)
  const crowd = Array.from({ length: 40 }, (_, index) => ({
    ...PROCESSES[3]!,
    pid: 8000 + index,
    ppid: 5012,
    name: index % 5 === 0 ? 'a_process_with_a_very_long_name_that_has_to_be_cut_short.exe' : `worker_${index}.exe`,
    end: index % 3 === 0 ? '2026-10-13T15:39:55.900000Z' : null,
  }))
  feedProcesses(live, crowd)
  await expect(page.locator('.live-process')).toHaveCount(PROCESSES.length + crowd.length)
  await expectNoVerticalScroll(page)
  await expectNoHorizontalOverflow(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-many-processes')
})

test('live-long-values-do-not-overflow', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  const live = await openLive(page, { analysis: runningAnalysis({ filename: `${'very_long_sample_name_'.repeat(8)}.exe` }) })
  stream(live)
  const longSummary = `powershell.exe wrote C:\\Users\\Analyst\\AppData\\Local\\Temp\\${'nested_directory_'.repeat(14)}payload.bin`
  const long = { ...NON_API_EVENTS[2]!, event: { ...NON_API_EVENTS[2]!.event, id: 'long' }, tartarus: { lane: 'file', summary: longSummary } }
  live.sendEvents([long])
  await expect(page.locator('.live-event__summary', { hasText: 'nested_directory_' })).toBeVisible()
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-long-values-narrow-600')
})

test('live-finished-handover', async ({ page }) => {
  let analysis = runningAnalysis()
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockEvolvingAnalysis(page, () => analysis)
  await mockViews(page)
  const live = await mockLiveSocket(page, ID)
  await page.goto(ROUTE)
  await live.connected()
  stream(live)
  await expect(page.locator('.live-event').first()).toBeVisible()
  await expect(page.locator('[data-live="finished"]')).toHaveCount(0)

  analysis = finishedAnalysis()
  live.send('status', { status: 'processing', phase: 'live', elapsed_s: 180, remaining_s: 0 })
  live.send('status', { status: 'done', phase: 'live', elapsed_s: 180, remaining_s: 0 })
  live.send('phase', { phase: 'final' })
  live.close(1000)

  await expect(page.locator('[data-live="finished"] img')).toBeVisible()
  await expect(page.locator('[data-field="link"]')).toContainText('STREAM ENDED')
  await expect(page.locator('.analysis-header')).toContainText('DONE')
  await expect(page.locator('.analysis-tabs [aria-selected="true"]')).toHaveText('LIVE')
  await expect(page.locator('[data-live="detections"]')).toHaveCount(0)
  await expect(page.locator('.live-event').first(), 'the stream keeps what it had').toBeVisible()
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-finished-handover')

  await page.getByRole('button', { name: '[SUMMARY]' }).click()
  await expect(page).toHaveURL(/\/analyses\/45\/summary$/)
  await expect(page.locator('.analysis-summary')).toBeVisible()
  await expect(page.locator('.analysis-tabs button', { hasText: 'LIVE' }), 'LIVE stays listed after leaving it').toHaveCount(1)

  await page.locator('.analysis-tabs button', { hasText: 'LIVE' }).click()
  await expect(page).toHaveURL(/\/analyses\/45\/live$/)
  await live.connected(2)
  live.send('status', { status: 'done', phase: 'final', elapsed_s: 180, remaining_s: 0 })
  live.send('phase', { phase: 'final' })
  live.close(1000)
  await expect(page.locator('[data-tab="live"]')).toBeVisible()
  await expect(page.locator('[data-live="finished"] img'), 'the finished panel is back').toBeVisible()
  await expect(page.locator('.analysis-tabs [aria-selected="true"]')).toHaveText('LIVE')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-returned-after-the-run')
})

test('live-leave-and-return-while-running', async ({ page }) => {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [runningAnalysis()] })
  await mockEvolvingAnalysis(page, () => runningAnalysis())
  await mockViews(page)
  const live = await mockLiveSocket(page, ID)
  await page.goto(ROUTE)
  await live.connected()
  stream(live)
  await expect(page.locator('.live-event').first()).toBeVisible()

  await page.locator('.analysis-tabs button', { hasText: 'SUMMARY' }).click()
  await expect(page.locator('.analysis-summary')).toBeVisible()
  await expect(page.locator('.analysis-tabs button', { hasText: 'LIVE' }), 'LIVE stays listed').toHaveCount(1)

  await page.locator('.analysis-tabs button', { hasText: 'LIVE' }).click()
  await live.connected(2)
  stream(live)
  await expect(page.locator('[data-tab="live"]')).toBeVisible()
  await expect(page.locator('.live-event').first()).toBeVisible()
  await expect(page.locator('.analysis-tabs [aria-selected="true"]')).toHaveText('LIVE')
  await expectNoVerticalScroll(page)
})

test('live-finished-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  let analysis = runningAnalysis()
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockEvolvingAnalysis(page, () => analysis)
  await mockViews(page)
  const live = await mockLiveSocket(page, ID)
  await page.goto(ROUTE)
  await live.connected()
  stream(live)
  analysis = finishedAnalysis()
  live.send('status', { status: 'done', phase: 'live', elapsed_s: 180, remaining_s: 0 })
  await expect(page.locator('[data-live="finished"] img')).toBeVisible()
  await expect(page.locator('.analysis-header')).toContainText('DONE')
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-finished-narrow-600')
})

test('live-not-offered-for-a-finished-analysis', async ({ page }) => {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [makeDetectedAnalysis({ id: ID })] })
  await mockViews(page)
  await page.goto(`${ROUTE}/live`)
  await expect(page.locator('.analysis-summary')).toBeVisible()
  await expect(page.locator('.analysis-tabs button', { hasText: 'LIVE' })).toHaveCount(0)
})
