import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { test as base, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { AnalysisRead, ErrorEnvelope, SettingsBody, SystemHealth } from '../../src/api/types.gen'

// An /api request no scenario mocked would fall through to the dev server's proxy (no backend
// behind it) and paint an error toast into the screenshot, so a mock whose URL drifted from
// what the app really requests (as a doubled /api/api prefix once did) produced a wrong picture
// without failing. This route is registered before each test's own mocks, and Playwright tries
// the most recently registered route first, so it only ever sees requests nothing else claimed.
// Matched on pathname, not a glob: Vite serves the app's own modules under /src/api/.
export const test = base.extend({
  page: async ({ page }, use) => {
    const unmocked: string[] = []
    await page.route(
      (url) => url.pathname.startsWith('/api/'),
      async (route) => {
        unmocked.push(route.request().url())
        await route.abort()
      },
    )
    await use(page)
    expect(unmocked, 'requests to /api that no scenario mocked').toEqual([])
  },
})

export { expect }

const SCREENSHOTS_DIR = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', 'screenshots')

export function screenshotPath(name: string): string {
  return path.join(SCREENSHOTS_DIR, `${name}.png`)
}

// Exact pathnames, not globs: '**/api/settings' would also match a doubled '/api/api/settings'
// and serve a request the real backend would 404.
function atPath(pathname: string): (url: URL) => boolean {
  return (url) => url.pathname === pathname
}

const HEALTH_URL = atPath('/api/system/health')
const SETTINGS_URL = atPath('/api/settings')
const WS_SYSTEM_URL = atPath('/ws/system')

// cape/guest have no backing service at all yet in this phase (no CAPE container, no guest
// VM orchestration — see MainLayout.vue's deferred-items comment), so "ok" for them is a state
// the app can never actually be in right now. Every shell fixture keeps them "down, not set up
// yet" and only varies postgres/opensearch, the two services this phase really has.
export const HEALTHY_SYSTEM: SystemHealth = {
  postgres: { status: 'ok', message: null },
  opensearch: { status: 'ok', message: null },
  cape: { status: 'down', message: 'not set up yet' },
  guest: { status: 'down', message: 'not set up yet' },
}

export const OPENSEARCH_DOWN_SYSTEM: SystemHealth = {
  ...HEALTHY_SYSTEM,
  opensearch: { status: 'down', message: 'connection refused' },
}

export async function mockHealthGet(page: Page, health: SystemHealth = HEALTHY_SYSTEM): Promise<void> {
  await page.route(HEALTH_URL, async (route) => {
    await route.fulfill({ json: health })
  })
}

/**
 * Mocks `/ws/system` at the WebSocket protocol level via `page.routeWebSocket` (Playwright
 * 1.48+). Not calling `connectToServer()` means Playwright fully mocks the socket rather than
 * forwarding to a real server, which is exactly what's wanted here: the dev server's own `/ws`
 * proxy target (`backend:8000`) does not exist in this harness's environment.
 */
export async function mockHealthWebSocket(
  page: Page,
  options: { health?: SystemHealth; closeImmediately?: boolean } = {},
): Promise<void> {
  const health = options.health ?? HEALTHY_SYSTEM
  await page.routeWebSocket(WS_SYSTEM_URL, (ws) => {
    if (options.closeImmediately) {
      void ws.close()
      return
    }
    ws.send(JSON.stringify({ type: 'health', ts: new Date().toISOString(), data: health }))
  })
}

/** The combination every route under MainLayout needs: a GET snapshot plus a live WS push. */
export async function mockShell(page: Page, health: SystemHealth = HEALTHY_SYSTEM): Promise<void> {
  await mockHealthGet(page, health)
  await mockHealthWebSocket(page, { health })
}

/**
 * Mocks `/ws/system` as a connection that opens, then is immediately closed by the far end —
 * reproducing what `ws.ts`'s `ReconnectingWebSocketClient` sees on a dropped connection, so it
 * lands in the `reconnecting` state the "Reconnecting…" bar renders for.
 */
export async function mockFlappingHealthWebSocket(page: Page): Promise<void> {
  await mockHealthWebSocket(page, { closeImmediately: true })
}

export async function mockSettings(
  page: Page,
  options: {
    getBody: SettingsBody
    getDelayMs?: number
    putResponse?: { status: number; body: SettingsBody | ErrorEnvelope }
  },
): Promise<void> {
  await page.route(SETTINGS_URL, async (route) => {
    const method = route.request().method()
    if (method === 'GET') {
      if (options.getDelayMs) await new Promise((resolve) => setTimeout(resolve, options.getDelayMs))
      await route.fulfill({ json: options.getBody })
      return
    }
    if (method === 'PUT' && options.putResponse) {
      await route.fulfill({ status: options.putResponse.status, json: options.putResponse.body })
      return
    }
    await route.fallback()
  })
}

export function validationErrorEnvelope(fields: { field: string; message: string }[]): ErrorEnvelope {
  return {
    error: {
      code: 'validation_error',
      message: 'Request validation failed',
      details: {
        fields: fields.map(({ field, message }) => ({ location: ['body', field], message, type: 'value_error' })),
      },
    },
  }
}

/**
 * Waits until Quasar has finished fading in every field's inline message. Playwright's
 * `toBeVisible()` counts an element at opacity 0 as visible, so without this a screenshot can
 * land mid-transition and show the field's error border with its message still invisible.
 */
export async function waitForFieldMessages(page: Page): Promise<void> {
  await page.waitForFunction(() =>
    [...document.querySelectorAll('.q-field__bottom')].every(
      (bottom) => bottom.getAnimations({ subtree: true }).length === 0,
    ),
  )
}

export const GUEST_READY_SYSTEM: SystemHealth = {
  ...HEALTHY_SYSTEM,
  cape: { status: 'ok', message: null },
  guest: { status: 'ok', message: null },
}

export const GUEST_NOT_READY_SYSTEM: SystemHealth = {
  ...HEALTHY_SYSTEM,
  guest: { status: 'down', message: 'no guest image built yet: build one from the Guest VM page' },
}

export const NARROW_AND_WIDE_WIDTHS = [600, 1280]

/** Playwright's `fullPage` capture would otherwise hide a page that scrolls sideways. */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  expect(scrollWidth, `page scrolls sideways: ${scrollWidth}px of content in a ${innerWidth}px window`).toBeLessThanOrEqual(
    innerWidth,
  )
}

export function errorEnvelope(code: string, message: string): ErrorEnvelope {
  return { error: { code, message, details: {} } }
}

const SUBMITTED_AT = '2026-10-12T09:14:03Z'

export function sha256Of(seed: number): string {
  return seed.toString(16).padStart(2, '0').repeat(32).slice(0, 64)
}

export function makeAnalysis(overrides: Partial<AnalysisRead> & Pick<AnalysisRead, 'id'>): AnalysisRead {
  return {
    sample_sha256: sha256Of(overrides.id),
    filename: `sample-${overrides.id}.exe`,
    cape_task_id: overrides.id + 100,
    status: 'queued',
    phase: 'final',
    options: { route: 'inetsim', timeout: 180 },
    score: null,
    max_severity: null,
    detected_families: [],
    event_count: 0,
    disk_bytes: 0,
    queue_position: null,
    error: null,
    submitted_at: SUBMITTED_AT,
    started_at: null,
    finished_at: null,
    summary: null,
    ...overrides,
  }
}

type MockedResponse<Body> = { status: number; body: Body; delayMs?: number }

export interface AnalysesMockOptions {
  items: AnalysisRead[]
  total?: number
  listDelayMs?: number
  listError?: MockedResponse<ErrorEnvelope>
  oneDelayMs?: number
  oneError?: MockedResponse<ErrorEnvelope>
  createResponse?: MockedResponse<AnalysisRead | ErrorEnvelope>
}

const ANALYSES_URL = atPath('/api/analyses')
const ANALYSIS_URL = (url: URL): boolean => /^\/api\/analyses\/\d+$/.test(url.pathname)
const CANCEL_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/cancel$/.test(url.pathname)

function idOf(url: string): number {
  return Number(new URL(url).pathname.split('/')[3])
}

function matchesFilters(analysis: AnalysisRead, params: URLSearchParams): boolean {
  const q = params.get('q')?.toLowerCase()
  const status = params.get('status')
  const matchesQuery = !q || analysis.filename.toLowerCase().includes(q) || analysis.sample_sha256.includes(q)
  return matchesQuery && (!status || analysis.status === status)
}

async function pause(ms: number | undefined): Promise<void> {
  if (ms) await new Promise((resolve) => setTimeout(resolve, ms))
}

/** Serves list, create, read, cancel and delete for `/api/analyses`, filtering the list like the backend. */
export async function mockAnalyses(page: Page, options: AnalysesMockOptions): Promise<void> {
  let items = [...options.items]

  await page.route(ANALYSES_URL, async (route) => {
    const request = route.request()
    if (request.method() === 'POST' && options.createResponse) {
      await pause(options.createResponse.delayMs)
      await route.fulfill({ status: options.createResponse.status, json: options.createResponse.body })
      return
    }
    if (request.method() !== 'GET') return route.fallback()
    await pause(options.listDelayMs)
    if (options.listError) {
      await route.fulfill({ status: options.listError.status, json: options.listError.body })
      return
    }
    const matching = items.filter((item) => matchesFilters(item, new URL(request.url()).searchParams))
    await route.fulfill({ json: { items: matching, total: options.total ?? matching.length } })
  })

  await page.route(ANALYSIS_URL, async (route) => {
    const method = route.request().method()
    const id = idOf(route.request().url())
    if (method === 'DELETE') {
      items = items.filter((item) => item.id !== id)
      await route.fulfill({ status: 204 })
      return
    }
    if (method !== 'GET') return route.fallback()
    await pause(options.oneDelayMs)
    const found = items.find((item) => item.id === id)
    if (options.oneError || !found) {
      const failure = options.oneError ?? { status: 404, body: errorEnvelope('not_found', `Analysis ${id} not found`) }
      await route.fulfill({ status: failure.status, json: failure.body })
      return
    }
    await route.fulfill({ json: found })
  })

  await page.route(CANCEL_URL, async (route) => {
    const id = idOf(route.request().url())
    items = items.map((item) => (item.id === id ? { ...item, status: 'cancelled' } : item))
    await route.fulfill({ json: items.find((item) => item.id === id) })
  })
}

const FINISHED_RUN = { started_at: '2026-10-12T09:14:30Z', finished_at: '2026-10-12T09:19:41Z' }

export function makeDetectedAnalysis(overrides: Partial<AnalysisRead> & Pick<AnalysisRead, 'id'>): AnalysisRead {
  return makeAnalysis({
    status: 'done',
    score: 8.4,
    max_severity: 'critical',
    detected_families: ['AgentTesla', 'Formbook'],
    event_count: 18432,
    ...FINISHED_RUN,
    summary: {
      duration_s: 311,
      process_count: 14,
      files_written: 37,
      registry_keys_written: 52,
      network: { dns: 9, hosts: 6, tcp: 23 },
      sample: { name: 'invoice_scan.exe', type: 'PE32 executable (GUI) Intel 80386' },
      signatures: [
        { name: 'injection_createremotethread', severity: 'high', description: 'Code injection with CreateRemoteThread in a remote process' },
        { name: 'ransomware_files', severity: 'critical', description: 'Appends a known ransomware file extension to files that have been encrypted' },
        { name: 'antivm_checks_available_memory', severity: 'low', description: 'Checks amount of memory in system, this can be used to detect virtual machines that have a low amount of memory available' },
        { name: 'persistence_autorun', severity: 'medium', description: 'Installs itself for autorun at Windows startup' },
        { name: 'network_http', severity: 'info', description: 'Performs some HTTP requests' },
      ],
      techniques: [
        { id: 'T1055', signatures: ['injection_createremotethread'] },
        { id: 'T1486', signatures: ['ransomware_files'] },
        { id: 'T1547.001', signatures: ['persistence_autorun'] },
        { id: 'T1497.001', signatures: ['antivm_checks_available_memory', 'antivm_generic_disk'] },
      ],
    },
    ...overrides,
  })
}

export function makeCleanAnalysis(overrides: Partial<AnalysisRead> & Pick<AnalysisRead, 'id'>): AnalysisRead {
  return makeAnalysis({
    status: 'done',
    score: 0,
    event_count: 912,
    ...FINISHED_RUN,
    summary: {
      duration_s: 311,
      process_count: 3,
      files_written: 1,
      registry_keys_written: 4,
      network: { dns: 0, hosts: 0, tcp: 0 },
      signatures: [],
      techniques: [],
    },
    ...overrides,
  })
}

/** One analysis in every status the Dashboard has to render. */
export const MIXED_ANALYSES: AnalysisRead[] = [
  makeAnalysis({ id: 9, status: 'queued', filename: 'dropper_stage2.dll' }),
  makeAnalysis({ id: 8, status: 'running', filename: 'payload.bin', started_at: '2026-10-12T09:14:30Z' }),
  makeAnalysis({ id: 7, status: 'processing', filename: 'setup_installer.msi', started_at: '2026-10-12T09:14:30Z' }),
  makeDetectedAnalysis({ id: 6, filename: 'invoice_scan.exe' }),
  makeDetectedAnalysis({ id: 5, filename: 'loader.ps1', score: 4.2, max_severity: 'medium' }),
  makeCleanAnalysis({ id: 4, filename: 'notepad_portable.exe' }),
  makeAnalysis({ id: 3, status: 'failed', filename: 'corrupt_sample.bin', error: 'CAPE could not start the guest' }),
  makeAnalysis({ id: 2, status: 'report_failed', filename: 'big_report.exe', error: 'report.json was truncated' }),
  makeAnalysis({ id: 1, status: 'cancelled', filename: 'cancelled_before_run.zip' }),
]

/** Waits out every finite CSS transition and animation (dialog and tooltip fades), ignoring endless spinners. */
export async function waitForTransitions(page: Page): Promise<void> {
  // A dialog's fade-in only registers as an animation on the frame after it mounts; checking
  // sooner finds nothing running and captures the dialog still transparent.
  await page.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
  )
  await page.waitForFunction(() =>
    document.getAnimations().every((animation) => animation.effect?.getComputedTiming().iterations === Infinity),
  )
}
