import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { test as base, expect } from '@playwright/test'
import { histogramOf, syntheticSource } from './timeline-data'
import type { Page, Route } from '@playwright/test'
import type {
  AnalysisRead,
  Annotations,
  ErrorEnvelope,
  Event,
  EventDetail,
  EventPage,
  FacetsRequest,
  FacetsResponse,
  FieldRead,
  FieldValues,
  FilterChip,
  HistogramRequest,
  QueryErrorRead,
  QueueSnapshot,
  RuleDetail,
  RuleRead,
  SearchRequest,
  SettingsBody,
  SystemHealth,
  TagUsageRead,
} from '../../src/api/types.gen'

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
const QUEUE_URL = atPath('/api/system/queue')

export const EMPTY_QUEUE: QueueSnapshot = { running: [], queued_count: 0, queued: [] }

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
  options: { health?: SystemHealth; queue?: QueueSnapshot; closeImmediately?: boolean } = {},
): Promise<void> {
  const health = options.health ?? HEALTHY_SYSTEM
  const queue = options.queue ?? EMPTY_QUEUE
  await page.routeWebSocket(WS_SYSTEM_URL, (ws) => {
    if (options.closeImmediately) {
      void ws.close()
      return
    }
    ws.send(JSON.stringify({ type: 'health', ts: new Date().toISOString(), data: health }))
    ws.send(JSON.stringify({ type: 'queue', ts: new Date().toISOString(), data: queue }))
  })
}

/** Serves `GET /api/system/queue`, the snapshot the queue store loads before any push. */
export async function mockQueueGet(page: Page, queue: QueueSnapshot = EMPTY_QUEUE): Promise<void> {
  await page.route(QUEUE_URL, (route) => route.fulfill({ json: queue }))
}

/** The combination every route under MainLayout needs: a GET snapshot plus a live WS push. */
export async function mockShell(page: Page, health: SystemHealth = HEALTHY_SYSTEM, queue: QueueSnapshot = EMPTY_QUEUE): Promise<void> {
  await mockHealthGet(page, health)
  await mockQueueGet(page, queue)
  await mockHealthWebSocket(page, { health, queue })
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
    kind: 'run',
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
    deadline_at: null,
    summary: null,
    tags: [],
    guest: null,
    guest_badges: [],
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
  const tag = params.get('tag')
  const matchesQuery = !q || analysis.filename.toLowerCase().includes(q) || analysis.sample_sha256.includes(q)
  return matchesQuery && (!status || analysis.status === status) && (!tag || analysis.tags.includes(tag))
}

async function pause(ms: number | undefined): Promise<void> {
  if (ms) await new Promise((resolve) => setTimeout(resolve, ms))
}

/** Serves list, create, read, cancel and delete for `/api/analyses`, filtering the list like the backend. */
export async function mockAnalyses(page: Page, options: AnalysesMockOptions): Promise<void> {
  let items = [...options.items]
  // Every page that lists or opens an analysis reads its tags and notes; a spec that is about them registers its own mock later.
  await mockAnnotations(page)

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

// ---------- Tags and notes: a stateful stand-in for /tags, /annotations, /tags/{id} and /notes/{id} ----------

type ErrorReply = { status: number; body: ErrorEnvelope; delayMs?: number }

export interface AnnotationsMockOptions {
  /** The annotations of the analysis as it opens; writes change this copy. */
  annotations?: Annotations
  /** What `GET /tags` answers: every tag in use with its count. */
  usage?: TagUsageRead[]
  readDelayMs?: number
  readError?: ErrorReply
  /** Answers every tag write with this instead of storing it (a 409 for a duplicate, a 422 for a bad name). */
  addTagError?: ErrorReply
  /** Answers every note write with this instead of storing it. */
  noteWriteError?: ErrorReply
  /** Makes note writes slow, to catch the editor saving. */
  noteWriteDelayMs?: number
}

const ANNOTATIONS_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/annotations$/.test(url.pathname)
const ADD_TAG_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/tags$/.test(url.pathname)
const TAG_LINK_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/tags\/\d+$/.test(url.pathname)
const ADD_NOTE_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/notes$/.test(url.pathname)
const NOTE_URL = (url: URL): boolean => /^\/api\/notes\/\d+$/.test(url.pathname)
const TAGS_URL = atPath('/api/tags')
const NOTE_TIMESTAMP = '2026-10-14T10:00:00Z'

/** Serves the annotation endpoints from one in-memory copy, so a tag added in a test shows on the next read. */
export async function mockAnnotations(page: Page, options: AnnotationsMockOptions = {}): Promise<void> {
  const stored: Annotations = {
    tags: [...(options.annotations?.tags ?? [])],
    notes: [...(options.annotations?.notes ?? [])],
  }
  let nextId = 1000
  const lastSegment = (route: Route): number => Number(new URL(route.request().url()).pathname.split('/').pop())
  const refuse = async (route: Route, error: ErrorReply): Promise<void> => {
    await pause(error.delayMs)
    await route.fulfill({ status: error.status, json: error.body })
  }

  await page.route(TAGS_URL, (route) => route.fulfill({ json: options.usage ?? [] }))

  await page.route(ANNOTATIONS_URL, async (route) => {
    await pause(options.readDelayMs)
    if (options.readError) return refuse(route, options.readError)
    await route.fulfill({ json: stored })
  })

  await page.route(ADD_TAG_URL, async (route) => {
    if (options.addTagError) return refuse(route, options.addTagError)
    const body = route.request().postDataJSON() as { target_type: 'analysis' | 'process' | 'event'; target_ref?: string; tag: string }
    const link = { link_id: nextId++, tag: body.tag.toLowerCase(), target_type: body.target_type, target_ref: body.target_ref ?? '', orphaned: false }
    stored.tags.push(link)
    await route.fulfill({ status: 201, json: link })
  })

  await page.route(TAG_LINK_URL, async (route) => {
    const id = lastSegment(route)
    stored.tags = stored.tags.filter((link) => link.link_id !== id)
    await route.fulfill({ status: 204 })
  })

  await page.route(ADD_NOTE_URL, async (route) => {
    await pause(options.noteWriteDelayMs)
    if (options.noteWriteError) return refuse(route, options.noteWriteError)
    const body = route.request().postDataJSON() as { target_type: 'analysis' | 'process' | 'event'; target_ref?: string; body: string }
    const note = { id: nextId++, target_type: body.target_type, target_ref: body.target_ref ?? '', body: body.body, created_at: NOTE_TIMESTAMP, updated_at: NOTE_TIMESTAMP, orphaned: false }
    stored.notes.push(note)
    await route.fulfill({ status: 201, json: note })
  })

  await page.route(NOTE_URL, async (route) => {
    await pause(options.noteWriteDelayMs)
    const id = lastSegment(route)
    if (route.request().method() === 'DELETE') {
      stored.notes = stored.notes.filter((note) => note.id !== id)
      return route.fulfill({ status: 204 })
    }
    if (options.noteWriteError) return refuse(route, options.noteWriteError)
    const { body } = route.request().postDataJSON() as { body: string }
    stored.notes = stored.notes.map((note) => (note.id === id ? { ...note, body } : note))
    await route.fulfill({ json: stored.notes.find((note) => note.id === id) })
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

// ---------- Analysis views (processes, network, ...): real responses of a real analysis ----------

const DATA_DIR = path.resolve(fileURLToPath(new URL('.', import.meta.url)), 'data')

export type ViewName = 'processes' | 'network' | 'registry' | 'detections' | 'attack' | 'iocs' | 'artifacts'

export interface ViewMock {
  body?: unknown
  status?: number
  delayMs?: number
}

/** What the backend answered for a real analysis (benign.exe and its child cmd.exe), as parsed JSON. */
export function realView<T = unknown>(name: ViewName | `process-${number}`): T {
  return JSON.parse(readFileSync(path.join(DATA_DIR, 'views', `${name}.json`), 'utf8')) as T
}

/**
 * Serves every view of an analysis from the real responses, so a tab (or the Overview) never meets
 * an unmocked request. `overrides` replaces, delays or fails any one view; `processes/{pid}` serves
 * the saved detail of pids 9708 and 2476 and `404` for any other pid; the screenshots are two real
 * guest screenshots. Register it after `mockAnalyses` (which serves the analysis itself).
 */
export async function mockViews(page: Page, overrides: Partial<Record<ViewName, ViewMock>> = {}): Promise<void> {
  const respond = async (route: Route, name: ViewName): Promise<void> => {
    const mock = overrides[name] ?? {}
    await pause(mock.delayMs)
    await route.fulfill({ status: mock.status ?? 200, json: mock.body ?? realView(name) })
  }
  const views: ViewName[] = ['processes', 'network', 'registry', 'detections', 'attack', 'iocs', 'artifacts']
  for (const name of views) {
    await page.route(
      (url) => new RegExp(`^/api/analyses/\\d+/${name}$`).test(url.pathname),
      (route) => respond(route, name),
    )
  }
  await page.route(
    (url) => /^\/api\/analyses\/\d+\/processes\/\d+$/.test(url.pathname),
    async (route) => {
      const pid = new URL(route.request().url()).pathname.split('/').pop()
      try {
        await route.fulfill({ json: realView(`process-${pid}` as `process-${number}`) })
      } catch {
        await route.fulfill({ status: 404, json: errorEnvelope('not_found', `Process ${pid} not found`) })
      }
    },
  )
  await page.route(
    (url) => /^\/api\/analyses\/\d+\/artifacts\/screenshots\/\d+$/.test(url.pathname),
    async (route) => {
      const n = Number(new URL(route.request().url()).pathname.split('/').pop())
      await route.fulfill({ contentType: 'image/jpeg', body: readFileSync(path.join(DATA_DIR, `shot-${(n % 2) + 1}.jpg`)) })
    },
  )
}

// ---------- The live tab: a scripted WebSocket and an analysis that changes under the page ----------

/** The 1280x720 window must hold the page exactly: nothing pushed below the fold, no vertical scroll. */
export async function expectNoVerticalScroll(page: Page): Promise<void> {
  const { scrollHeight, innerHeight } = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
  }))
  expect(scrollHeight, `page scrolls vertically: ${scrollHeight}px of content in a ${innerHeight}px window`).toBeLessThanOrEqual(innerHeight)
}

interface LiveSubscription {
  lanes?: string[]
  pids?: number[]
  include_api?: boolean
}

export interface LiveEventDoc {
  tartarus: { lane: string }
  process?: { pid?: number }
}

// The server's own rule (backend hub.py), written again here so the mock filters like the real thing.
function passesSubscription(event: LiveEventDoc, subscription: LiveSubscription): boolean {
  const lane = event.tartarus.lane
  const namesApi = subscription.lanes?.includes('api') ?? false
  if (lane === 'api' && !subscription.include_api && !namesApi) return false
  if (subscription.lanes && !subscription.lanes.includes(lane)) return false
  return !subscription.pids || (event.process?.pid !== undefined && subscription.pids.includes(event.process.pid))
}

export interface LiveSocketMock {
  /** Resolves once the page has opened its `n`th connection. */
  connected(n?: number): Promise<void>
  /** One server message to the newest connection. */
  send(type: string, data: unknown): void
  /** An `events` message holding only the events the client's last `subscribe` asks for, as the server sends them. */
  sendEvents(events: LiveEventDoc[], dropped?: number): void
  close(code: number): void
  /** The `subscribe` payloads the page sent, oldest first. */
  subscriptions(): LiveSubscription[]
}

/** Mocks `WS /ws/analyses/{id}/live`; the test plays the server, message by message. */
export async function mockLiveSocket(page: Page, analysisId: number): Promise<LiveSocketMock> {
  const sockets: { send(message: string): void; close(options: { code: number; reason: string }): void }[] = []
  const subscriptions: LiveSubscription[] = []

  await page.routeWebSocket(atPath(`/ws/analyses/${analysisId}/live`), (ws) => {
    sockets.push(ws)
    ws.onMessage((message) => {
      const parsed = JSON.parse(String(message)) as { type: string; data: LiveSubscription }
      if (parsed.type === 'subscribe') subscriptions.push(parsed.data)
    })
  })

  const newest = () => sockets[sockets.length - 1]!
  const mock: LiveSocketMock = {
    async connected(n = 1) {
      await expect.poll(() => sockets.length, { message: `waiting for live connection ${n}` }).toBeGreaterThanOrEqual(n)
      await expect.poll(() => subscriptions.length, { message: 'waiting for the first subscribe' }).toBeGreaterThanOrEqual(n)
    },
    send(type, data) {
      newest().send(JSON.stringify({ type, ts: new Date().toISOString(), data }))
    },
    sendEvents(events, dropped = 0) {
      const subscription = subscriptions[subscriptions.length - 1] ?? {}
      mock.send('events', { events: events.filter((event) => passesSubscription(event, subscription)), dropped })
    },
    close(code) {
      newest().close({ code, reason: '' })
    },
    subscriptions: () => subscriptions,
  }
  return mock
}

/** Serves `GET /api/analyses/{id}` from `current()` on every call, so a test can finish the analysis between two polls. */
export async function mockEvolvingAnalysis(page: Page, current: () => AnalysisRead): Promise<void> {
  await page.route(ANALYSIS_URL, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    await route.fulfill({ json: current() })
  })
}

// ---------- The query bar: the real field catalog (79 fields, exported from the backend) and plausible values ----------

const QUERY_FIELDS_URL = atPath('/api/query/fields')
const QUERY_VALIDATE_URL = atPath('/api/query/validate')
const QUERY_VALUES_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/query\/values$/.test(url.pathname)
const FIELD_REFERENCE = /(?<![\w."@:-])([A-Za-z@][\w.@-]*)(?=:|\s*(?:>=|<=|>|<))/g
const MAX_SUGGESTION_DISTANCE = 3

export function realFieldCatalog(): FieldRead[] {
  return JSON.parse(readFileSync(path.join(DATA_DIR, 'query', 'fields.json'), 'utf8')) as FieldRead[]
}

function realValues(): Record<string, { value: string; count: number }[]> {
  return JSON.parse(readFileSync(path.join(DATA_DIR, 'query', 'values.json'), 'utf8'))
}

/** `suggest_fields` of the backend: by name prefix, then alias prefix, then inside a name. */
function suggestFields(catalog: FieldRead[], prefix: string): FieldRead[] {
  const needle = prefix.toLowerCase()
  const searchable = catalog.filter((field) => field.searchable)
  const byName = searchable.filter((field) => field.name.toLowerCase().startsWith(needle))
  const byAlias = searchable.filter((field) => !byName.includes(field) && field.aliases.some((alias) => alias.startsWith(needle)))
  const inside = searchable.filter((field) => ![...byName, ...byAlias].includes(field) && field.name.toLowerCase().includes(needle))
  return [...byName, ...byAlias, ...inside].slice(0, 50)
}

function editDistance(a: string, b: string): number {
  let previous = Array.from({ length: b.length + 1 }, (_, index) => index)
  for (let i = 1; i <= a.length; i++) {
    const row = [i]
    for (let j = 1; j <= b.length; j++) {
      row.push(Math.min(previous[j]! + 1, row[j - 1]! + 1, previous[j - 1]! + (a[i - 1] === b[j - 1] ? 0 : 1)))
    }
    previous = row
  }
  return previous[b.length]!
}

/** What the backend's compiler answers for an unknown field: its span and the closest known name. */
function unknownFieldErrors(catalog: FieldRead[], query: string): QueryErrorRead[] {
  const known = catalog.flatMap((field) => [field.name, ...field.aliases])
  const errors: QueryErrorRead[] = []
  for (const match of query.matchAll(FIELD_REFERENCE)) {
    const name = match[1]!
    const insideQuotes = (query.slice(0, match.index).match(/"/g)?.length ?? 0) % 2 === 1
    if (insideQuotes || known.some((candidate) => candidate.toLowerCase() === name.toLowerCase())) continue
    const closest = known
      .map((candidate) => ({ candidate, distance: editDistance(name.toLowerCase(), candidate.toLowerCase()) }))
      .filter(({ distance }) => distance <= MAX_SUGGESTION_DISTANCE)
      .sort((a, b) => a.distance - b.distance)[0]?.candidate
    errors.push({
      start: match.index,
      end: match.index + name.length,
      message: closest ? `unknown field '${name}'; did you mean '${closest}'?` : `unknown field '${name}'`,
      suggestion: closest ?? null,
    })
  }
  return errors
}

export interface QueryMockOptions {
  /** Replaces the default validator (unknown fields only) for a scenario that needs another error. */
  validate?: (query: string) => QueryErrorRead[]
  /** Makes `GET /query/fields` and the values answer slowly, to catch the bar in its loading state. */
  delayMs?: number
}

/**
 * Serves the query bar's three endpoints: the field catalog with its prefix search, the values of a
 * keyword field, and validation (by default it only finds unknown fields, with a "did you mean").
 * Register it after `mockAnalyses`.
 */
export async function mockQuery(page: Page, options: QueryMockOptions = {}): Promise<void> {
  const catalog = realFieldCatalog()
  const values = realValues()
  const validate = options.validate ?? ((query: string) => unknownFieldErrors(catalog, query))

  await page.route(QUERY_FIELDS_URL, async (route) => {
    await pause(options.delayMs)
    const prefix = new URL(route.request().url()).searchParams.get('prefix')
    await route.fulfill({ json: prefix ? suggestFields(catalog, prefix) : catalog })
  })

  await page.route(QUERY_VALIDATE_URL, async (route) => {
    const { query } = route.request().postDataJSON() as { query: string }
    const errors = validate(query)
    await route.fulfill({ json: { ok: errors.length === 0, errors } })
  })

  await page.route(QUERY_VALUES_URL, async (route) => {
    await pause(options.delayMs)
    const params = new URL(route.request().url()).searchParams
    const requested = (params.get('field') ?? '').toLowerCase()
    const field = catalog.find((entry) => entry.name.toLowerCase() === requested || entry.aliases.includes(requested))
    const prefix = (params.get('prefix') ?? '').toLowerCase()
    const limit = Number(params.get('limit') ?? 10)
    const matching = (field ? (values[field.name] ?? []) : []).filter((entry) => entry.value.startsWith(prefix))
    const body: FieldValues = { values: matching.slice(0, limit) }
    await route.fulfill({ json: body })
  })
}

// ---------- The Events tab: sample events (250, all six lanes and the detection kind), searched, faceted and detailed ----------

const EVENTS_SEARCH_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/events\/search$/.test(url.pathname)
const EVENTS_FACETS_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/events\/facets$/.test(url.pathname)
const EVENTS_HISTOGRAM_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/events\/histogram$/.test(url.pathname)
const EVENT_DETAIL_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/events\/[^/]+$/.test(url.pathname) && !url.pathname.endsWith('/search')
const FACET_TOP = 10

interface RelatedSpec {
  ids: string[]
  total: number
}

interface DetailSpec {
  source: Record<string, unknown>
  references: RelatedSpec
  referenced_by: RelatedSpec
}

interface EventsSample {
  details: Record<string, DetailSpec>
  /** Ids of the events that have a hand-written detail, by what each one shows. */
  special: { api: string; alert: string; bigAlert: string; longProcess: string; longFile: string }
}

export function sampleEvents(): Event[] {
  const typed = JSON.parse(readFileSync(path.join(DATA_DIR, 'events', 'events.json'), 'utf8')) as Omit<Event, 'fields'>[]
  return typed.map((event) => ({ ...event, fields: {} }))
}

export function sampleEventDetails(): EventsSample {
  return JSON.parse(readFileSync(path.join(DATA_DIR, 'events', 'details.json'), 'utf8')) as EventsSample
}

type Source = Record<string, unknown>

const MAX_COLUMNS = 12

function sampleSources(): Record<string, Source> {
  return JSON.parse(readFileSync(path.join(DATA_DIR, 'events', 'sources.json'), 'utf8')) as Record<string, Source>
}

/** The value at a dotted catalog name of a stored document, read by its nested path. */
function valueAt(source: Source, field: string): unknown {
  if (field in source) return source[field]
  return field.split('.').reduce<unknown>((node, key) => (node && typeof node === 'object' ? (node as Source)[key] : undefined), source)
}

function leafTexts(value: unknown): string[] {
  if (value === null || value === undefined || value === '') return []
  if (Array.isArray(value)) return value.flatMap(leafTexts)
  return typeof value === 'object' ? [] : [String(value)]
}

/** The query compiler's resolution of a name or alias: the catalog fields it stands for (a composite alias has several). */
function resolveFields(requested: string): string[] {
  const wanted = requested.toLowerCase()
  const field = realFieldCatalog().find((entry) => entry.name.toLowerCase() === wanted || entry.aliases.includes(wanted))
  if (!field) return [requested]
  return field.members.length > 0 ? field.members : [field.name]
}

/** The values an event has for a catalog field or alias, as text, from its stored document. */
function fieldValues(sources: Record<string, Source>, event: Event, requested: string): string[] {
  const source = sources[event.id]
  return source ? resolveFields(requested).flatMap((field) => leafTexts(valueAt(source, field))) : []
}

function wildcard(pattern: string): RegExp {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')
  return new RegExp(`^${escaped}$`, 'i')
}

function matchesChip(sources: Record<string, Source>, event: Event, chip: FilterChip): boolean {
  const matches = fieldValues(sources, event, chip.field).some((value) => wildcard(chip.value).test(value))
  return chip.negate ? !matches : matches
}

/** The values a term's right side accepts: one, or the members of a `(a OR b)` group, unquoted. */
function alternativesOf(value: string): string[] {
  const members = value.startsWith('(') ? value.slice(1, -1).split(/\s+OR\s+/) : [value]
  return members.map((member) => member.replace(/^"|"$/g, ''))
}

/** The query language reduced to what a sample needs: ANDed `field:value` and `field:(a OR b)` terms and free words, with NOT. */
function matchesQuery(sources: Record<string, Source>, event: Event, query: string): boolean {
  const terms = query.match(/NOT\s+|[^\s"]+:"[^"]*"|[^\s"]+:\([^)]*\)|[^\s]+/g) ?? []
  let negate = false
  for (const term of terms) {
    if (/^NOT\s*$/.test(term)) {
      negate = true
      continue
    }
    if (term.toUpperCase() === 'AND') continue
    const split = term.indexOf(':')
    const hit =
      split > 0
        ? fieldValues(sources, event, term.slice(0, split)).some((value) => alternativesOf(term.slice(split + 1)).some((pattern) => wildcard(pattern).test(value)))
        : (event.summary ?? '').toLowerCase().includes(term.replace(/"/g, '').toLowerCase())
    if (hit === negate) return false
    negate = false
  }
  return true
}

/** `ownFields`: the chips on these catalog fields are left out, as the backend does for a facet's own field. */
function filterEvents(sources: Record<string, Source>, events: Event[], body: Partial<FacetsRequest>, ownFields: string[] = []): Event[] {
  const { query, filters = [], time_range: range, lanes, pids } = body
  const applied = filters.filter((chip) => !resolveFields(chip.field).some((field) => ownFields.includes(field)))
  return events.filter(
    (event) =>
      (!query || matchesQuery(sources, event, query)) &&
      applied.every((chip) => matchesChip(sources, event, chip)) &&
      (!range?.from || event.time >= range.from) &&
      (!range?.to || event.time <= range.to) &&
      (!lanes || lanes.includes(event.lane as never)) &&
      (!pids || pids.includes(event.process?.pid ?? -1)),
  )
}

function facetsOf(sources: Record<string, Source>, events: Event[], body: FacetsRequest): FacetsResponse {
  return {
    facets: (body.fields ?? []).map((field) => {
      const counts = new Map<string, number>()
      let total = 0
      for (const event of filterEvents(sources, events, body, resolveFields(field))) {
        const values = fieldValues(sources, event, field)
        if (values.length > 0) total++
        for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
      }
      const values = [...counts]
        .sort(([a, x], [b, y]) => y - x || a.localeCompare(b))
        .slice(0, FACET_TOP)
        .map(([value, count]) => ({ value, count }))
      return { field, values, total }
    }),
  }
}

/** The canonical names of the requested columns, or the 422 the backend answers for one it cannot show. */
function resolveColumns(columns: string[]): { names: string[] } | { invalid: string } {
  if (columns.length > MAX_COLUMNS) return { invalid: `at most ${MAX_COLUMNS} columns` }
  const catalog = realFieldCatalog()
  const names: string[] = []
  for (const column of columns) {
    const wanted = column.toLowerCase()
    const field = catalog.find((entry) => entry.name.toLowerCase() === wanted || entry.aliases.includes(wanted))
    if (!field || !field.searchable || field.members.length > 0) return { invalid: column }
    if (!names.includes(field.name)) names.push(field.name)
  }
  return { names }
}

function withColumns(sources: Record<string, Source>, event: Event, names: string[]): Event {
  const source = sources[event.id]
  const fields: Event['fields'] = {}
  for (const name of names) {
    const value = source ? valueAt(source, name) : undefined
    if (value !== undefined && value !== null && value !== '') fields[name] = value as Event['fields'][string]
  }
  return { ...event, fields }
}

function detailOf(sources: Record<string, Source>, event: Event, all: Event[], spec: DetailSpec | undefined): EventDetail {
  const listing = (related: RelatedSpec | undefined) => ({
    items: (related?.ids ?? []).map((id) => all.find((known) => known.id === id)).filter((known): known is Event => known !== undefined),
    total: related?.total ?? 0,
  })
  return {
    event,
    source: spec?.source ?? sources[event.id] ?? {},
    related: { references: listing(spec?.references), referenced_by: listing(spec?.referenced_by) },
    annotations: { tags: [], notes: [] },
  }
}

export interface EventsMockOptions {
  /** Replaces the sample events (pass `[]` for an analysis with none). */
  events?: Event[]
  /** Makes search answer slowly, to catch the table in its loading state. */
  searchDelayMs?: number
  facetsDelayMs?: number
  /** Makes the histogram (the Timeline's overview and its range data) answer slowly, to catch the canvas loading. */
  histogramDelayMs?: number
  detailDelayMs?: number
  /** Answers every search with this error instead of a page. */
  searchFailure?: { status: number; code: string; message: string }
  /** Narrows `searchFailure` to the searches this accepts (the events table's pages, not the timeline's own). */
  searchFailureWhen?: (body: SearchRequest) => boolean
  facetsFailure?: { status: number; code: string; message: string }
  /** Answers every histogram with this error, while search still works. */
  histogramFailure?: { status: number; code: string; message: string }
  /** Answers the detail of these event ids with an error; every other id is served from the sample. */
  detailFailures?: Record<string, { status: number; code: string; message: string }>
  /** Answers the second and later pages of a search slowly, to catch the loading-more footer. */
  nextPageDelayMs?: number
}

export interface EventsMock {
  searches: SearchRequest[]
  facetRequests: FacetsRequest[]
  histogramRequests: HistogramRequest[]
  detailRequests: string[]
}

/**
 * Serves the Events and Timeline tabs' endpoints from the sample events (or `options.events`, an event
 * without a stored document getting a small generated one so chips and queries still match it): `events/search` (the chips, the
 * simple query terms, pids, a time range and both sorts, paged by an opaque cursor), `events/facets`
 * (the top ten of each field over the filtered events, ignoring the chips on the field itself) and `events/{id}` (a hand-written document for
 * a few events, the stored sample document for the rest, and the related events resolved from the sample)
 * and `events/histogram` (the span, epoch-aligned buckets by lane and the alerts of the same filtered events, as the backend counts them).
 * Register it after `mockAnalyses` and `mockQuery`.
 */
export async function mockEvents(page: Page, options: EventsMockOptions = {}): Promise<EventsMock> {
  const all = options.events ?? sampleEvents()
  const { details } = sampleEventDetails()
  const sampled = sampleSources()
  const sources = { ...Object.fromEntries(all.filter((event) => !(event.id in sampled)).map((event) => [event.id, syntheticSource(event)])), ...sampled }
  const mock: EventsMock = { searches: [], facetRequests: [], histogramRequests: [], detailRequests: [] }
  const failure = (route: Route, error: { status: number; code: string; message: string }) =>
    route.fulfill({ status: error.status, json: errorEnvelope(error.code, error.message) })

  await page.route(EVENTS_SEARCH_URL, async (route) => {
    const body = route.request().postDataJSON() as SearchRequest
    mock.searches.push(body)
    await pause(body.search_after ? options.nextPageDelayMs ?? options.searchDelayMs : options.searchDelayMs)
    if (options.searchFailure && (options.searchFailureWhen?.(body) ?? true)) return failure(route, options.searchFailure)
    const columns = resolveColumns(body.columns ?? [])
    if ('invalid' in columns) return failure(route, { status: 422, code: 'invalid_column', message: `${columns.invalid} cannot be shown as a column` })
    const matched = filterEvents(sources, all, body)
    const sorted = body.sort === '-@timestamp' ? [...matched].reverse() : matched
    const offset = body.search_after ? Number(JSON.parse(Buffer.from(body.search_after, 'base64url').toString()).after) : 0
    const size = body.size ?? 100
    const next = offset + size
    const pageBody: EventPage = {
      events: sorted.slice(offset, next).map((event) => withColumns(sources, event, columns.names)),
      total: sorted.length,
      next_cursor: next < sorted.length ? Buffer.from(JSON.stringify({ sort: body.sort, after: next })).toString('base64url') : null,
    }
    await route.fulfill({ json: pageBody })
  })

  await page.route(EVENTS_FACETS_URL, async (route) => {
    const body = route.request().postDataJSON() as FacetsRequest
    mock.facetRequests.push(body)
    await pause(options.facetsDelayMs)
    if (options.facetsFailure) return failure(route, options.facetsFailure)
    await route.fulfill({ json: facetsOf(sources, all, body) })
  })

  await page.route(EVENTS_HISTOGRAM_URL, async (route) => {
    const body = route.request().postDataJSON() as HistogramRequest
    mock.histogramRequests.push(body)
    await pause(options.histogramDelayMs)
    if (options.histogramFailure) return failure(route, options.histogramFailure)
    await route.fulfill({ json: histogramOf(filterEvents(sources, all, body), body.time_range, body.interval) })
  })

  await page.route(EVENT_DETAIL_URL, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!)
    mock.detailRequests.push(id)
    await pause(options.detailDelayMs)
    const forced = options.detailFailures?.[id]
    if (forced) return failure(route, forced)
    const event = all.find((known) => known.id === id)
    if (!event) return failure(route, { status: 404, code: 'not_found', message: `Event ${id} not found` })
    await route.fulfill({ json: detailOf(sources, event, all, details[id]) })
  })

  return mock
}

// ---------- The Rules page: the list, one rule's file, the enabled switch and the reload ----------

type RuleFailure = { status: number; body: ErrorEnvelope }

export interface RulesMockOptions {
  rules: RuleRead[]
  yaml?: (rule: RuleRead) => string
  listDelayMs?: number
  listError?: RuleFailure
  /** What a reload answers; the list as served when absent. */
  reloaded?: RuleRead[]
  reloadDelayMs?: number
  reloadError?: RuleFailure
  readDelayMs?: number
  readError?: RuleFailure
  updateError?: RuleFailure
}

const RULES_URL = atPath('/api/rules')
const RULES_RELOAD_URL = atPath('/api/rules/reload')
const RULE_URL = (url: URL): boolean => /^\/api\/rules\/[^/]+$/.test(url.pathname) && url.pathname !== '/api/rules/reload'

/** Serves `GET /api/rules`, `POST /api/rules/reload`, and `GET`/`PATCH /api/rules/{id}` over one list that the switch changes. */
export async function mockRules(page: Page, options: RulesMockOptions): Promise<void> {
  let rules = [...options.rules]
  const fail = async (route: Route, failure: RuleFailure) => route.fulfill({ status: failure.status, json: failure.body })

  await page.route(RULES_URL, async (route) => {
    await pause(options.listDelayMs)
    if (options.listError) return fail(route, options.listError)
    await route.fulfill({ json: rules })
  })

  await page.route(RULES_RELOAD_URL, async (route) => {
    await pause(options.reloadDelayMs)
    if (options.reloadError) return fail(route, options.reloadError)
    rules = [...(options.reloaded ?? rules)]
    await route.fulfill({ json: rules })
  })

  await page.route(RULE_URL, async (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!)
    const rule = rules.find((known) => known.id === id)
    if (route.request().method() === 'PATCH') {
      if (options.updateError || !rule) return fail(route, options.updateError ?? { status: 404, body: errorEnvelope('not_found', `Rule ${id} not found`) })
      const { enabled } = route.request().postDataJSON() as { enabled: boolean }
      rules = rules.map((known) => (known.id === id ? { ...known, enabled } : known))
      return route.fulfill({ json: rules.find((known) => known.id === id) })
    }
    await pause(options.readDelayMs)
    if (options.readError) return fail(route, options.readError)
    if (!rule) return fail(route, { status: 404, body: errorEnvelope('not_found', `Rule ${id} not found`) })
    const detail: RuleDetail = { ...rule, yaml: options.yaml?.(rule) ?? `title: ${rule.title}\nid: ${rule.id}\n` }
    await route.fulfill({ json: detail })
  })
}
