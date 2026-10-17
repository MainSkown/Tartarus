import type { Locator, Page } from '@playwright/test'
import type { AnalysisRead } from '../../src/api/types.gen'
import { errorEnvelope, expect, realView, screenshotPath, waitForTransitions, type LiveSocketMock } from './fixtures'

export interface SessionProcess {
  pid: number
  ppid: number | null
  name: string
  executable: string
  command_line: string
  start: string
  end: string | null
}

export interface SessionEvent {
  '@timestamp': string
  event: { id: string; action: string; sequence: number; severity: number }
  tartarus: { lane: string; summary: string }
  process: { pid: number; name: string }
}

interface RealProcessView {
  roots: { pid: number; ppid: number; name: string; executable: string; command_line: string; start: string; end: string; children: RealProcessView['roots'] }[]
}

const real = realView<RealProcessView>('processes')
const [benign] = real.roots
const [cmd] = benign!.children

const live = (process: NonNullable<typeof benign>, end: string | null): SessionProcess => ({
  pid: process.pid,
  ppid: process.ppid,
  name: process.name,
  executable: process.executable,
  command_line: process.command_line,
  start: process.start,
  end,
})

// benign.exe and its cmd.exe come from the real analysis; the rest are invented so the tree has depth to grow into.
export const PROCESSES: SessionProcess[] = [
  live(benign!, null),
  live(cmd!, cmd!.end),
  {
    pid: 3120,
    ppid: cmd!.pid,
    name: 'conhost.exe',
    executable: 'C:\\Windows\\System32\\conhost.exe',
    command_line: '\\??\\C:\\Windows\\system32\\conhost.exe 0x4',
    start: '2026-10-13T15:39:51.101000Z',
    end: '2026-10-13T15:39:51.480000Z',
  },
  {
    pid: 5012,
    ppid: benign!.pid,
    name: 'powershell.exe',
    executable: 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
    command_line: 'powershell.exe -NoProfile -WindowStyle Hidden -EncodedCommand SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA',
    start: '2026-10-13T15:39:52.310000Z',
    end: null,
  },
  {
    pid: 6188,
    ppid: 5012,
    name: 'whoami.exe',
    executable: 'C:\\Windows\\System32\\whoami.exe',
    command_line: 'whoami.exe /all',
    start: '2026-10-13T15:39:53.002000Z',
    end: '2026-10-13T15:39:53.140000Z',
  },
  {
    pid: 7340,
    ppid: 5012,
    name: 'schtasks.exe',
    executable: 'C:\\Windows\\System32\\schtasks.exe',
    command_line: 'schtasks.exe /create /tn Updater /tr C:\\Users\\Analyst\\AppData\\Roaming\\updater.exe /sc onlogon',
    start: '2026-10-13T15:39:54.220000Z',
    end: null,
  },
]

const API_WEIGHTS: [string, number][] = (realView<{ top_apis: { name: string; count: number }[] }>('process-9708').top_apis).map(
  ({ name, count }) => [name, count],
)

const derived = (pid: number, action: string, lane: string, summary: string, at: string): SessionEvent => ({
  '@timestamp': at,
  event: { id: '', action, sequence: 0, severity: 0 },
  tartarus: { lane, summary },
  process: { pid, name: PROCESSES.find((process) => process.pid === pid)!.name },
})

const REAL_DERIVED: SessionEvent[] = [
  derived(2476, 'process-created', 'process', 'benign.exe started cmd.exe /c ver', '2026-10-13T15:39:50.753000Z'),
  derived(9708, 'file-created', 'file', 'benign.exe created C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt', '2026-10-13T15:39:51.487000Z'),
  derived(9708, 'file-written', 'file', 'benign.exe wrote C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt', '2026-10-13T15:39:51.503000Z'),
  derived(9708, 'reg-key-created', 'registry', 'benign.exe created key HKEY_CURRENT_USER\\Software\\Tartarus', '2026-10-13T15:39:51.503000Z'),
  derived(9708, 'reg-value-set', 'registry', 'benign.exe set HKEY_CURRENT_USER\\Software\\Tartarus\\SelfTest', '2026-10-13T15:39:51.503000Z'),
  derived(9708, 'dns-query', 'network', 'benign.exe resolved tartarus-selftest.example', '2026-10-13T15:39:51.565000Z'),
  derived(2476, 'process-terminated', 'process', 'cmd.exe terminated', '2026-10-13T15:39:51.491000Z'),
]

const INVENTED_DERIVED: SessionEvent[] = [
  derived(5012, 'process-created', 'process', 'benign.exe started powershell.exe -NoProfile -WindowStyle Hidden -EncodedCommand SQBFAFgA…', '2026-10-13T15:39:52.310000Z'),
  derived(5012, 'file-created', 'file', 'powershell.exe created C:\\Users\\Analyst\\AppData\\Local\\Temp\\__PSScriptPolicyTest_k3x1.ps1', '2026-10-13T15:39:52.402000Z'),
  derived(5012, 'file-deleted', 'file', 'powershell.exe deleted C:\\Users\\Analyst\\AppData\\Local\\Temp\\__PSScriptPolicyTest_k3x1.ps1', '2026-10-13T15:39:52.431000Z'),
  derived(5012, 'dns-query', 'network', 'powershell.exe resolved updates.tartarus-selftest.example', '2026-10-13T15:39:52.880000Z'),
  derived(5012, 'network-connection', 'network', 'powershell.exe connected to 192.168.150.1:443', '2026-10-13T15:39:52.912000Z'),
  derived(5012, 'process-created', 'process', 'powershell.exe started whoami.exe /all', '2026-10-13T15:39:53.002000Z'),
  derived(6188, 'process-terminated', 'process', 'whoami.exe terminated', '2026-10-13T15:39:53.140000Z'),
  derived(5012, 'file-written', 'file', 'powershell.exe wrote C:\\Users\\Analyst\\AppData\\Roaming\\updater.exe', '2026-10-13T15:39:53.604000Z'),
  derived(5012, 'reg-value-set', 'registry', 'powershell.exe set HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Updater', '2026-10-13T15:39:53.931000Z'),
  derived(5012, 'process-created', 'process', 'powershell.exe started schtasks.exe /create /tn Updater /tr C:\\Users\\Analyst\\AppData\\Roaming\\updater.exe /sc onlogon', '2026-10-13T15:39:54.220000Z'),
  derived(7340, 'file-created', 'file', 'schtasks.exe created C:\\Windows\\System32\\Tasks\\Updater', '2026-10-13T15:39:54.470000Z'),
  derived(7340, 'reg-key-created', 'registry', 'schtasks.exe created key HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Schedule\\TaskCache\\Tree\\Updater', '2026-10-13T15:39:54.512000Z'),
  derived(7340, 'reg-value-set', 'registry', 'schtasks.exe set HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Schedule\\TaskCache\\Tree\\Updater\\Id', '2026-10-13T15:39:54.513000Z'),
  derived(5012, 'inject-thread', 'process', 'powershell.exe created a remote thread in pid 4410', '2026-10-13T15:39:55.210000Z'),
]

function hexId(seed: number): string {
  let state = (seed + 1) * 2654435761
  let id = ''
  while (id.length < 40) {
    state = (state * 1103515245 + 12345) % 2147483648
    id += state.toString(16).padStart(8, '0')
  }
  return id.slice(0, 40)
}

function isoAt(start: string, offsetMs: number): string {
  return new Date(Date.parse(start) + offsetMs).toISOString().replace('Z', '000Z')
}

// Deterministic, so every run of the harness draws the same stream.
function apiEvents(count: number): SessionEvent[] {
  const total = API_WEIGHTS.reduce((sum, [, weight]) => sum + weight, 0)
  const names = API_WEIGHTS.flatMap(([name, weight]) => Array<string>(Math.round((weight / total) * 100)).fill(name))
  return Array.from({ length: count }, (_, index) => {
    const process = PROCESSES[index % PROCESSES.length]!
    const lifetimeMs = (process.end ? Date.parse(process.end) : Date.parse('2026-10-13T15:39:56Z')) - Date.parse(process.start)
    const api = names[(index * 7) % names.length]!
    return {
      '@timestamp': isoAt(process.start, ((index * 37) % 1000) * (lifetimeMs / 1000)),
      event: { id: '', action: 'api-call', sequence: 0, severity: 0 },
      tartarus: { lane: 'api', summary: `${process.name} called ${api}` },
      process: { pid: process.pid, name: process.name },
    }
  })
}

function sequenced(events: SessionEvent[], firstSequence = 0): SessionEvent[] {
  return [...events]
    .sort((a, b) => a['@timestamp'].localeCompare(b['@timestamp']))
    .map((event, index) => ({ ...event, event: { ...event.event, id: hexId(firstSequence + index), sequence: firstSequence + index } }))
}

/** About 300 capemon-like events of the whole run in time order: the semantic ones first, the api calls between them. */
export const SESSION_EVENTS: SessionEvent[] = sequenced([...REAL_DERIVED, ...INVENTED_DERIVED, ...apiEvents(286)])

export const NON_API_EVENTS: SessionEvent[] = SESSION_EVENTS.filter((event) => event.tartarus.lane !== 'api')

/** Plain api-call events with ids that do not collide with the session's, for streams long enough to hit the local bound. */
export function fillerEvents(count: number, firstSequence = 100_000): SessionEvent[] {
  return sequenced(apiEvents(count), firstSequence)
}

export function laneCounts(events: SessionEvent[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const event of events) counts[event.tartarus.lane] = (counts[event.tartarus.lane] ?? 0) + 1
  return counts
}

export function countsMessage(events: SessionEvent[]): { by_lane: Record<string, number>; by_severity: Record<string, number>; total: number } {
  return { by_lane: laneCounts(events), by_severity: { info: events.length, low: 0, medium: 0, high: 0, critical: 0 }, total: events.length }
}

export const RUNNING_STATUS = { status: 'running', phase: 'live', elapsed_s: 14.2, remaining_s: 165.8 }

export interface EndpointAnswer {
  status: number
  json: AnalysisRead | ReturnType<typeof errorEnvelope>
}

export function refusal(status: number, message: string): EndpointAnswer {
  return { status, json: errorEnvelope(status === 409 ? 'conflict' : 'bad_gateway', message) }
}

type Answer = () => EndpointAnswer | Promise<EndpointAnswer>

/** `answer` is asked on every request, so a test can change its mind; a promise it returns holds the response back. */
async function mockPost(page: Page, pathname: string, answer: Answer): Promise<{ requests: () => number }> {
  let requests = 0
  await page.route(
    (url) => url.pathname === pathname,
    async (route) => {
      requests += 1
      const { status, json } = await answer()
      await route.fulfill({ status, json })
    },
  )
  return { requests: () => requests }
}

/** Plays `POST /api/analyses/{id}/finish`. */
export function mockFinish(page: Page, id: number, answer: Answer): Promise<{ requests: () => number }> {
  return mockPost(page, `/api/analyses/${id}/finish`, answer)
}

/** Plays `POST /api/analyses/{id}/extend`. */
export function mockExtend(page: Page, id: number, answer: Answer): Promise<{ requests: () => number }> {
  return mockPost(page, `/api/analyses/${id}/extend`, answer)
}

export const endRunButton = (page: Page) => page.locator('[data-live="end-run"]')
export const extendRunButton = (page: Page) => page.locator('[data-live="extend-run"]')
const confirmDialog = (page: Page) => page.locator('.q-dialog')

export function feedProcesses(live: LiveSocketMock, processes: SessionProcess[]): void {
  for (const { pid, ppid, name, executable, command_line, start, end } of processes) {
    const node = { pid, ppid, name, executable, command_line, start, end: null }
    live.send('process', { op: 'add', node })
    if (end !== null) live.send('process', { op: 'end', node: { ...node, end } })
  }
}

export function stream(live: LiveSocketMock, processes = PROCESSES.length, events = NON_API_EVENTS): void {
  live.send('status', RUNNING_STATUS)
  feedProcesses(live, PROCESSES.slice(0, processes))
  live.sendEvents(events)
  live.send('counts', countsMessage(SESSION_EVENTS))
}

export async function expectPanelsInsideViewport(page: Page): Promise<void> {
  const { innerHeight } = await page.evaluate(() => ({ innerHeight: window.innerHeight }))
  for (const part of ['status', 'processes', 'stream']) {
    const box = (await page.locator(`[data-live="${part}"]`).boundingBox())!
    expect(box.y + box.height, `${part} reaches below the window`).toBeLessThanOrEqual(innerHeight)
  }
}

export async function snapshot(page: Page, name: string, options: { toast?: boolean } = {}): Promise<void> {
  // A pointer left over a button from the last click would paint its hover state into the picture.
  await page.mouse.move(0, 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  // A toast's progress bar is a finite animation that ends with the toast, so waiting it out would photograph an empty corner.
  if (options.toast) await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  else await waitForTransitions(page)
  await page.screenshot({ path: screenshotPath(name), fullPage: true })
}

export async function pressEndRun(page: Page): Promise<void> {
  await endRunButton(page).click()
  await confirmDialog(page).getByRole('button', { name: 'END RUN' }).click()
  await expect(confirmDialog(page), 'the dialog fades out before anything is photographed').toHaveCount(0)
}

export async function expectInsideStatusBar(page: Page, button: Locator, name: string): Promise<void> {
  const bar = (await page.locator('[data-live="status"]').boundingBox())!
  const box = (await button.boundingBox())!
  expect(box.x, `${name} starts left of the bar`).toBeGreaterThanOrEqual(bar.x)
  expect(box.x + box.width, `${name} ends right of the bar`).toBeLessThanOrEqual(bar.x + bar.width)
  expect(box.y + box.height, `${name} sticks out of the bar`).toBeLessThanOrEqual(bar.y + bar.height)
}

export function expectEndRunInsideStatusBar(page: Page): Promise<void> {
  return expectInsideStatusBar(page, endRunButton(page), 'the end-run button')
}
