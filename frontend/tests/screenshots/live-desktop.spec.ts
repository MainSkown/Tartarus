import type { Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import { instruction, mockDesktopSocket, type DesktopSocketMock } from './desktop-mock'
import {
  GUEST_READY_SYSTEM,
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
  endRunButton,
  expectEndRunInsideStatusBar,
  mockFinish,
  pressEndRun,
} from './live-session'
const RUN_ENDED = 'The run has ended. CAPE is processing the results.'

const ID = 45
const ROUTE = `/analyses/${ID}`
// The browser reports whole pixels, which the display's scale turns into a few guest pixels of rounding.
const MOUSE_TOLERANCE = 12
const LONG_REASON = `desktop not available yet ${'because the guest has not started its display server '.repeat(4)}`

const screen = (page: Page) => page.locator('[data-desktop="screen"]')
const message = (page: Page) => page.locator('[data-desktop="message"]')

function interactiveAnalysis(overrides: Partial<AnalysisRead> = {}): AnalysisRead {
  return makeAnalysis({
    id: ID,
    status: 'running',
    filename: 'invoice_scan.exe',
    started_at: '2026-10-13T15:39:20Z',
    options: { route: 'inetsim', timeout: 180, interactive: true },
    ...overrides,
  })
}

interface Opened {
  live: LiveSocketMock
  desktop: DesktopSocketMock
}

async function openDesktop(page: Page, analysis: AnalysisRead = interactiveAnalysis()): Promise<Opened> {
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockViews(page)
  const live = await mockLiveSocket(page, ID)
  const desktop = await mockDesktopSocket(page, ID)
  await page.goto(ROUTE)
  await live.connected()
  live.send('status', RUNNING_STATUS)
  return { live, desktop }
}

async function connectToGuest({ desktop }: Opened, page: Page): Promise<void> {
  await desktop.connected()
  desktop.admit()
  desktop.sendFrame()
  await expect(message(page)).toHaveCount(0)
  await expectFramePainted(page)
}

async function expectFramePainted(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(() => {
        const canvas = document.querySelector<HTMLCanvasElement>('[data-desktop="screen"] canvas')
        if (!canvas || canvas.width === 0 || canvas.height === 0) return 0
        const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data
        let lit = 0
        for (let at = 0; at < pixels.length; at += 4) if (pixels[at]! + pixels[at + 1]! + pixels[at + 2]! > 60) lit += 1
        return lit
      }),
      { message: 'the guest picture is not on the display canvas' },
    )
    .toBeGreaterThan(50_000)
}

async function snapshot(page: Page, name: string): Promise<void> {
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

async function expectPanelsInsideViewport(page: Page): Promise<void> {
  const { innerHeight } = await page.evaluate(() => ({ innerHeight: window.innerHeight }))
  for (const part of ['status', 'desktop', 'processes', 'stream']) {
    const box = (await page.locator(`[data-live="${part}"]`).boundingBox())!
    expect(box.y + box.height, `${part} reaches below the window`).toBeLessThanOrEqual(innerHeight)
  }
}

async function expectDisplayInsideScreen(page: Page): Promise<void> {
  const frame = (await screen(page).boundingBox())!
  const display = (await page.locator('.live-desktop__stage > div').boundingBox())!
  expect(display.width / display.height, 'the display keeps the guest\'s 16:10').toBeCloseTo(1.6, 1)
  expect(display.x).toBeGreaterThanOrEqual(frame.x)
  expect(display.y).toBeGreaterThanOrEqual(frame.y)
  expect(display.x + display.width).toBeLessThanOrEqual(frame.x + frame.width + 1)
  expect(display.y + display.height).toBeLessThanOrEqual(frame.y + frame.height + 1)
}

function lastPressedMouse(desktop: DesktopSocketMock): { x: number; y: number } | undefined {
  const pressed = desktop
    .fromBrowser()
    .map((frame) => /^5\.mouse,\d+\.(\d+),\d+\.(\d+),1\.1;$/.exec(frame))
    .filter((match): match is RegExpExecArray => match !== null)
    .at(-1)
  return pressed && { x: Number(pressed[1]), y: Number(pressed[2]) }
}

function keysSent(desktop: DesktopSocketMock): string[] {
  return desktop.fromBrowser().filter((frame) => frame.startsWith('3.key,'))
}

test('live-desktop-connecting', async ({ page }) => {
  const { desktop } = await openDesktop(page)
  await desktop.connected()
  await expect(message(page)).toContainText('connecting to the desktop')
  await expect(page.locator('.pane-heading', { hasText: 'DESKTOP' })).toBeVisible()
  await expect(page.locator('[data-desktop="ctrl-alt-del"]')).toBeDisabled()
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-connecting')
})

test('live-desktop-waiting-for-the-guest', async ({ page }) => {
  const { desktop } = await openDesktop(page, interactiveAnalysis({ status: 'starting' }))
  await desktop.connected()
  desktop.admit()
  await expect(message(page)).toContainText('waiting for the guest to start')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-waiting')
})

test('live-desktop-not-available-yet-retries', async ({ page }) => {
  const { desktop } = await openDesktop(page)
  await desktop.connected()
  desktop.admit()
  desktop.close(4408, 'desktop not available yet')
  await expect(message(page)).toContainText('desktop not available yet')
  await expect(page.locator('[data-desktop="retry"]')).toHaveText('[RETRY]')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-not-available-yet')

  await page.locator('[data-desktop="retry"]').click()
  await desktop.connected(2)
  await expect(message(page)).toContainText('connecting to the desktop')
})

test('live-desktop-connected-shows-the-guest', async ({ page }) => {
  const opened = await openDesktop(page)
  stream(opened.live)
  await connectToGuest(opened, page)
  await expect(page.locator('[data-desktop="ctrl-alt-del"]')).toBeEnabled()
  await expect(screen(page)).toHaveAttribute('data-captured', 'false')
  await expectDisplayInsideScreen(page)
  await expect(page.locator('.live-process')).toHaveCount(PROCESSES.length)
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-desktop-connected')
})

test('live-desktop-keyboard-only-while-focused', async ({ page }) => {
  const opened = await openDesktop(page)
  await connectToGuest(opened, page)
  const { desktop } = opened

  await page.keyboard.press('a')
  await page.waitForTimeout(150)
  expect(keysSent(desktop), 'a key typed before the panel has focus').toEqual([])

  await screen(page).click()
  await expect(screen(page)).toHaveAttribute('data-captured', 'true')
  await expect(page.locator('[data-desktop="toolbar-note"]')).toContainText('Esc Esc to release')
  await page.keyboard.press('a')
  await expect.poll(() => keysSent(desktop)).toContain('3.key,2.97,1.1;')
  await snapshot(page, 'live-desktop-focused')

  await page.locator('.analysis-header').click()
  await expect(screen(page)).toHaveAttribute('data-captured', 'false')
  const before = keysSent(desktop).length
  await page.keyboard.press('b')
  await page.waitForTimeout(150)
  expect(keysSent(desktop).length, 'a key typed after the panel lost focus').toBe(before)
})

test('live-desktop-escape-twice-releases-the-keyboard', async ({ page }) => {
  const opened = await openDesktop(page)
  await connectToGuest(opened, page)
  await screen(page).click()
  await expect(screen(page)).toHaveAttribute('data-captured', 'true')
  await page.keyboard.press('Escape')
  await expect(screen(page)).toHaveAttribute('data-captured', 'true')
  await page.keyboard.press('Escape')
  await expect(screen(page)).toHaveAttribute('data-captured', 'false')
  await expect(screen(page)).not.toBeFocused()
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.waitForTimeout(1200)
  expect(pageErrors, 'a key repeat left running after the release').toEqual([])
})

test('live-desktop-mouse-reaches-the-guest', async ({ page }) => {
  const opened = await openDesktop(page)
  await connectToGuest(opened, page)
  const display = (await page.locator('.live-desktop__stage > div').boundingBox())!
  await page.mouse.move(display.x + display.width / 2, display.y + display.height / 2)
  await page.mouse.down()
  await page.mouse.up()
  await expect
    .poll(() => {
      const at = lastPressedMouse(opened.desktop)
      return at !== undefined && Math.abs(at.x - 640) <= MOUSE_TOLERANCE && Math.abs(at.y - 400) <= MOUSE_TOLERANCE
    })
    .toBe(true)
})

test('live-desktop-ctrl-alt-del-button', async ({ page }) => {
  const opened = await openDesktop(page)
  await connectToGuest(opened, page)
  await page.locator('[data-desktop="ctrl-alt-del"]').click()
  await expect.poll(() => keysSent(opened.desktop)).toEqual([
    '3.key,5.65507,1.1;',
    '3.key,5.65513,1.1;',
    '3.key,5.65535,1.1;',
    '3.key,5.65535,1.0;',
    '3.key,5.65513,1.0;',
    '3.key,5.65507,1.0;',
  ])
})

test('live-desktop-run-ended', async ({ page }) => {
  const opened = await openDesktop(page)
  await connectToGuest(opened, page)
  opened.desktop.close(1000, 'analysis is no longer running')
  await expect(message(page)).toContainText(RUN_ENDED)
  await expect(message(page)).not.toContainText('analysis is no longer running')
  await expect(message(page)).not.toContainText('NaN')
  await expect(page.locator('[data-desktop="retry"]'), 'a run that ended cannot be reconnected').toHaveCount(0)
  await expect(page.locator('[data-desktop="ctrl-alt-del"]')).toBeDisabled()
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-run-ended')
})

test('live-desktop-dropped-connection-reconnects', async ({ page }) => {
  const opened = await openDesktop(page)
  await connectToGuest(opened, page)
  opened.desktop.close(1006, '')
  await expect(message(page)).toContainText('the desktop connection was lost')
  await expect(message(page)).not.toContainText('The run has ended')
  await expect(page.locator('[data-desktop="retry"]')).toHaveText('[RECONNECT]')
  await expect(page.locator('[data-desktop="ctrl-alt-del"]')).toBeDisabled()
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-disconnected')

  await page.locator('[data-desktop="retry"]').click()
  await opened.desktop.connected(2)
  await expect(message(page)).toContainText('connecting to the desktop')
})

test('live-desktop-end-run-ends-the-desktop-calmly', async ({ page }) => {
  const opened = await openDesktop(page)
  stream(opened.live)
  await connectToGuest(opened, page)
  const finish = await mockFinish(page, ID, () => ({ status: 200, json: interactiveAnalysis() }))
  await expect(endRunButton(page)).toBeEnabled()
  await expectEndRunInsideStatusBar(page)
  await pressEndRun(page)
  await expect(endRunButton(page)).toContainText('ENDING...')
  expect(finish.requests()).toBe(1)
  await expect(message(page), 'the picture stays while the guest is still stopping').toHaveCount(0)

  opened.desktop.send(instruction('error', 'Aborted. See logs.', 519))
  opened.desktop.close(1000, 'desktop reported an error')
  await expect(message(page)).toContainText(RUN_ENDED)
  await expect(page.locator('[data-desktop="retry"]')).toHaveCount(0)
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-desktop-end-run-ended')
})

test('live-desktop-end-run-then-a-dropped-socket-is-still-the-end', async ({ page }) => {
  const opened = await openDesktop(page)
  stream(opened.live)
  await connectToGuest(opened, page)
  await mockFinish(page, ID, () => ({ status: 200, json: interactiveAnalysis() }))
  await pressEndRun(page)
  opened.desktop.close(1006, '')
  await expect(message(page)).toContainText(RUN_ENDED)
  await expect(page.locator('[data-desktop="retry"]')).toHaveCount(0)
})

test('live-desktop-guest-is-off', async ({ page }) => {
  const { desktop } = await openDesktop(page)
  await desktop.connected()
  desktop.admit()
  desktop.send(instruction('ready', 'guac-5d0a1c76'), instruction('error', 'Unable to connect to VNC server', 519))
  desktop.close(1000, 'desktop reported an error')
  await expect(message(page)).toContainText('the guest is not running')
  await expect(message(page)).toContainText('Unable to connect to VNC server')
  await expect(page.locator('[data-desktop="retry"]')).toHaveText('[RETRY]')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-guest-off')
})

test('live-desktop-service-unreachable', async ({ page }) => {
  const { desktop } = await openDesktop(page)
  await desktop.connected()
  desktop.admit()
  desktop.close(1011, 'desktop service unavailable')
  await expect(message(page)).toContainText('the desktop service is unreachable')
  await expect(page.locator('[data-desktop="retry"]')).toHaveText('[RETRY]')
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-unreachable')
})

test('live-desktop-not-running-yet-for-a-queued-analysis', async ({ page }) => {
  const { desktop } = await openDesktop(page, interactiveAnalysis({ status: 'queued', started_at: null, queue_position: 1 }))
  await expect(message(page)).toContainText('only available while the analysis runs')
  expect(desktop.connections()).toBe(0)
  await expect(page.locator('[data-desktop="retry"]')).toHaveCount(0)
  await expectNoVerticalScroll(page)
  await snapshot(page, 'live-desktop-queued')
})

test('live-desktop-finished-shows-the-last-screenshot', async ({ page }) => {
  let analysis = interactiveAnalysis()
  await mockShell(page, GUEST_READY_SYSTEM)
  await mockAnalyses(page, { items: [analysis] })
  await mockEvolvingAnalysis(page, () => analysis)
  await mockViews(page)
  const live = await mockLiveSocket(page, ID)
  const desktop = await mockDesktopSocket(page, ID)
  await page.goto(ROUTE)
  await live.connected()
  stream(live)
  await connectToGuest({ live, desktop }, page)

  analysis = makeDetectedAnalysis({
    id: ID,
    filename: 'invoice_scan.exe',
    started_at: '2026-10-13T15:39:20Z',
    finished_at: '2026-10-13T15:42:31Z',
    options: { route: 'inetsim', timeout: 180, interactive: true },
  })
  desktop.send(instruction('error', 'Aborted. See logs.', 519))
  desktop.close(1000, 'desktop reported an error')
  live.send('status', { status: 'done', phase: 'live', elapsed_s: 180, remaining_s: 0 })
  live.send('phase', { phase: 'final' })
  live.close(1000)

  await expect(page.locator('[data-desktop="last-screenshot"]')).toBeVisible()
  await expect(message(page)).toContainText(RUN_ENDED)
  await expect(message(page)).not.toContainText('only available while')
  await expect(page.locator('[data-live="finished"] img')).toBeVisible()
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-desktop-finished')
})

test('live-desktop-long-reason-stays-inside-at-600px', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  const { desktop } = await openDesktop(page)
  await desktop.connected()
  desktop.admit()
  desktop.close(4408, LONG_REASON)
  await expect(message(page)).toContainText('desktop not available yet')
  await expectNoHorizontalOverflow(page)
  const frame = (await screen(page).boundingBox())!
  const text = (await page.locator('.desktop-message__body').boundingBox())!
  expect(text.x).toBeGreaterThanOrEqual(frame.x)
  expect(text.x + text.width).toBeLessThanOrEqual(frame.x + frame.width + 1)
  await snapshot(page, 'live-desktop-long-reason-narrow-600')
})

test('live-desktop-interactive-tab-1280x720', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const opened = await openDesktop(page)
  stream(opened.live)
  await connectToGuest(opened, page)
  await expect(page.locator('.live-event').first()).toBeVisible()
  await expectDisplayInsideScreen(page)
  await expectEndRunInsideStatusBar(page)
  await expectNoHorizontalOverflow(page)
  await expectNoVerticalScroll(page)
  await expectPanelsInsideViewport(page)
  await snapshot(page, 'live-desktop-tab-1280x720')
})

test('live-desktop-interactive-tab-narrow-600', async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 900 })
  const opened = await openDesktop(page)
  stream(opened.live)
  await connectToGuest(opened, page)
  await expectDisplayInsideScreen(page)
  await expectEndRunInsideStatusBar(page)
  await expectNoHorizontalOverflow(page)
  await snapshot(page, 'live-desktop-tab-narrow-600')
})

function stream(live: LiveSocketMock): void {
  live.send('status', RUNNING_STATUS)
  for (const { pid, ppid, name, executable, command_line, start, end } of PROCESSES) {
    const node = { pid, ppid, name, executable, command_line, start, end: null }
    live.send('process', { op: 'add', node })
    if (end !== null) live.send('process', { op: 'end', node: { ...node, end } })
  }
  live.sendEvents(NON_API_EVENTS)
  live.send('counts', countsMessage(SESSION_EVENTS))
}
