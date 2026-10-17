import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import { mockDesktopSocket, type DesktopSocketMock } from './desktop-mock'
import {
  GUEST_READY_SYSTEM,
  NARROW_AND_WIDE_WIDTHS,
  expect,
  expectNoHorizontalOverflow,
  expectNoVerticalScroll,
  makeAnalysis,
  mockAnalyses,
  mockEvolvingAnalysis,
  mockLiveSocket,
  mockShell,
  mockViews,
  test,
  type LiveSocketMock,
} from './fixtures'
import {
  endRunButton,
  expectInsideStatusBar,
  expectPanelsInsideViewport,
  extendRunButton,
  mockExtend,
  refusal,
  snapshot,
  stream,
} from './live-session'

const ID = 45
const ROUTE = `/analyses/${ID}`
const WIDE = Math.max(...NARROW_AND_WIDE_WIDTHS)
const NARROW = Math.min(...NARROW_AND_WIDE_WIDTHS)
const PHONE = 390
const LONGEST_RUN_MESSAGE = 'The run is already at its longest (20 minutes)'

interface RunClock {
  remainingS: number
  startedAgoS: number
}

const DEFAULT_CLOCK: RunClock = { remainingS: 200, startedAgoS: 400 }
const EXTENDED_CLOCK: RunClock = { remainingS: 260, startedAgoS: 400 }

const isoAt = (ms: number) => new Date(ms).toISOString()

/** The deadline sits `remainingS` from now, so the header and the status bar show the same time left. */
function interactiveRun({ remainingS, startedAgoS }: RunClock): AnalysisRead {
  const now = Date.now()
  return makeAnalysis({
    id: ID,
    status: 'running',
    filename: 'invoice_scan.exe',
    started_at: isoAt(now - startedAgoS * 1000),
    deadline_at: isoAt(now + remainingS * 1000),
    options: { route: 'inetsim', timeout: 1200, interactive: true },
  })
}

function plainRun(): AnalysisRead {
  return makeAnalysis({
    id: ID,
    status: 'running',
    filename: 'invoice_scan.exe',
    started_at: isoAt(Date.now() - DEFAULT_CLOCK.startedAgoS * 1000),
    options: { route: 'inetsim', timeout: 180 },
  })
}

interface OpenedRun {
  live: LiveSocketMock
  desktop: DesktopSocketMock
}

async function openRun(page: Page, analysis: AnalysisRead, route = ROUTE): Promise<OpenedRun> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockEvolvingAnalysis(page, () => analysis)
  await mockViews(page)
  const live = await mockLiveSocket(page, ID)
  const desktop = await mockDesktopSocket(page, ID)
  await page.goto(route)
  return { live, desktop }
}

function sendClock(live: LiveSocketMock, { remainingS, startedAgoS }: RunClock): void {
  live.send('status', { status: 'running', phase: 'live', elapsed_s: startedAgoS, remaining_s: remainingS })
}

async function openInteractiveRun(page: Page, clock: RunClock = DEFAULT_CLOCK): Promise<OpenedRun> {
  const opened = await openRun(page, interactiveRun(clock))
  await opened.live.connected()
  await opened.desktop.connected()
  opened.desktop.admit()
  opened.desktop.sendFrame()
  stream(opened.live)
  sendClock(opened.live, clock)
  await expect(page.locator('.live-event').first()).toBeVisible()
  return opened
}

const remainingField = (page: Page) => page.locator('[data-field="remaining"]')
const warningCountdown = (page: Page) => page.locator('[data-field="remaining"] .run-countdown--warning')

test('live-extend-default', async ({ page }) => {
  await page.setViewportSize({ width: WIDE, height: 720 })
  await openInteractiveRun(page)
  await expect(remainingField(page)).toContainText(/3m (19|20)s/)
  await expect(extendRunButton(page)).toHaveText('[+60S]')
  await expect(extendRunButton(page)).toBeEnabled()
  await expect(endRunButton(page)).toContainText('END RUN')
  await expectInsideStatusBar(page, extendRunButton(page), 'the +60S button')
  await expectInsideStatusBar(page, endRunButton(page), 'the end-run button')
  await expectNoHorizontalOverflow(page)
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-extend-default')
})

test('live-extend-warning', async ({ page }) => {
  await page.setViewportSize({ width: WIDE, height: 720 })
  await openInteractiveRun(page, { remainingS: 24, startedAgoS: 400 })
  await expect(warningCountdown(page)).toContainText(/2[0-4]s/)
  await expectInsideStatusBar(page, extendRunButton(page), 'the +60S button')
  await expectNoHorizontalOverflow(page)
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-extend-warning')
})

test('live-extend-ending', async ({ page }) => {
  await page.setViewportSize({ width: WIDE, height: 720 })
  await openInteractiveRun(page, { remainingS: 0, startedAgoS: 400 })
  await expect(warningCountdown(page)).toHaveText('ending')
  await expect(extendRunButton(page), 'the run still runs, so it can still be extended').toBeEnabled()
  await expectInsideStatusBar(page, extendRunButton(page), 'the +60S button')
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-extend-ending')
})

test('live-extend-extending-then-extended', async ({ page }) => {
  await page.setViewportSize({ width: WIDE, height: 720 })
  const opened = await openInteractiveRun(page)
  let release = (): void => {}
  const held = new Promise<void>((resolve) => (release = resolve))
  const extend = await mockExtend(page, ID, async () => {
    await held
    return { status: 200, json: interactiveRun(EXTENDED_CLOCK) }
  })

  await extendRunButton(page).click()
  await expect(extendRunButton(page)).toBeDisabled()
  await expect.poll(() => extend.requests(), { message: 'the press sends one extend request' }).toBe(1)
  await expectInsideStatusBar(page, extendRunButton(page), 'the +60S button')
  await snapshot(page, 'live-extend-extending')

  release()
  await expect(extendRunButton(page)).toBeEnabled()
  sendClock(opened.live, EXTENDED_CLOCK)
  await expect(remainingField(page)).toContainText(/4m (19|20)s/)
  await expect(page.locator('.tt-toast--warning'), 'an accepted extension shows no warning').toHaveCount(0)
  await expectInsideStatusBar(page, extendRunButton(page), 'the +60S button')
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-extend-extended')
})

test('live-extend-at-longest', async ({ page }) => {
  await page.setViewportSize({ width: WIDE, height: 720 })
  await openInteractiveRun(page, { remainingS: 600, startedAgoS: 600 })
  await expect(extendRunButton(page)).toBeDisabled()
  await expect(page.locator('.live-extend-run')).toHaveAttribute('title', LONGEST_RUN_MESSAGE)
  await page.locator('.live-extend-run').hover()
  await expectInsideStatusBar(page, extendRunButton(page), 'the +60S button')
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-extend-at-longest')
})

test('live-extend-refused', async ({ page }) => {
  await page.setViewportSize({ width: WIDE, height: 720 })
  await openInteractiveRun(page)
  const extend = await mockExtend(page, ID, () => refusal(409, LONGEST_RUN_MESSAGE))

  await extendRunButton(page).click()
  await expect(page.locator('.tt-toast--warning')).toContainText(LONGEST_RUN_MESSAGE)
  await expect(page.locator('.tt-toast--error'), 'a refused extension is a warning, not an error').toHaveCount(0)
  await expect(extendRunButton(page)).toBeEnabled()
  expect(extend.requests()).toBe(1)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-extend-refused', { toast: true })
})

test('live-extend-non-interactive', async ({ page }) => {
  await page.setViewportSize({ width: WIDE, height: 720 })
  const opened = await openRun(page, plainRun())
  await opened.live.connected()
  stream(opened.live)
  await expect(page.locator('.live-event').first()).toBeVisible()
  await expect(remainingField(page)).toContainText(/2m \d+s/)
  await expect(extendRunButton(page), 'a run that cannot be extended offers no +60S').toHaveCount(0)
  await expect(warningCountdown(page)).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-extend-non-interactive')
})

for (const width of [NARROW, PHONE]) {
  test(`live-extend-narrow-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === NARROW ? 900 : 844 })
    await openInteractiveRun(page)
    await expect(extendRunButton(page)).toBeEnabled()
    await expectInsideStatusBar(page, extendRunButton(page), 'the +60S button')
    await expectInsideStatusBar(page, endRunButton(page), 'the end-run button')
    await expectNoHorizontalOverflow(page)
    await snapshot(page, `live-extend-narrow-${width}`)
  })
}

for (const width of [WIDE, NARROW, PHONE]) {
  test(`live-extend-header-${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === WIDE ? 720 : 900 })
    await openRun(page, interactiveRun(DEFAULT_CLOCK), `${ROUTE}/summary`)
    await expect(page.locator('.analysis-tabs [aria-selected="true"]')).toHaveText('SUMMARY')
    await expect(page.locator('.analysis-header__remaining')).toContainText('REMAINING')
    await expect(page.locator('.analysis-header__remaining')).toContainText(/3m (19|20)s/)
    await expectNoHorizontalOverflow(page)
    await snapshot(page, `live-extend-header-${width}`)
  })
}
