import type { Event, Histogram, HistogramRequest, Lane, TimeRange } from '../../src/api/types.gen'

// Generated analyses for the Timeline tab. The 250 sample events cover every lane but are sparse; these
// add a dense run (thousands of events, in bursts) for the count bars and a handful of events
// milliseconds apart for the deepest zoom. Everything is deterministic: the same pictures every run.

const DENSE_COUNT = 6000
const SEED = 20261013
const API_CALLS = ['NtWriteFile', 'NtCreateFile', 'RegSetValueExW', 'NtDelayExecution', 'CreateProcessInternalW', 'InternetOpenUrlW', 'NtAllocateVirtualMemory']
// Share of the events in each lane; the API lane is the loud background stream (design system, "Event categories").
const LANE_WEIGHTS: [Lane, number][] = [
  ['api', 0.55],
  ['file', 0.17],
  ['registry', 0.12],
  ['network', 0.07],
  ['process', 0.05],
  ['memory', 0.04],
]
const LANE_ACTIONS: Record<Lane, string> = {
  api: 'api-call',
  file: 'file-written',
  registry: 'registry-value-set',
  network: 'network-flow',
  process: 'process-created',
  memory: 'memory-allocated',
}
const BURST_SHARE = 0.35
const BURST_COUNT = 7
const BURST_SPREAD_MS = 700

function randomGenerator(seed: number): () => number {
  let state = seed
  return () => {
    state = (state * 48271) % 2147483647
    return state / 2147483647
  }
}

function pickLane(draw: number): Lane {
  let cumulative = 0
  for (const [lane, weight] of LANE_WEIGHTS) {
    cumulative += weight
    if (draw < cumulative) return lane
  }
  return 'api'
}

function summaryOf(lane: Lane, api: string, processName: string, index: number): string {
  switch (lane) {
    case 'api':
      return `${processName} called ${api}`
    case 'file':
      return `${processName} wrote C:\\Users\\anna\\AppData\\Local\\Temp\\tmp${index}.dat`
    case 'registry':
      return `${processName} set HKCU\\Software\\Vendor\\Key${index % 40}`
    case 'network':
      return `${processName} connected to 192.168.150.${(index % 200) + 1}:443`
    case 'process':
      return `${processName} started worker${index % 9}.exe`
    case 'memory':
      return `${processName} allocated ${(index % 16) + 1} MiB`
  }
}

/** The sample's events plus ~6000 generated ones in bursts over the same 50 seconds; the sample's alerts stay as the detections. */
export function denseEvents(sample: Event[]): Event[] {
  const random = randomGenerator(SEED)
  const processes = [...new Map(sample.filter((event) => event.process?.pid).map((event) => [event.process!.pid, event.process!])).values()]
  const first = Date.parse(sample[0]!.time)
  const last = Date.parse(sample[sample.length - 1]!.time)
  const centres = Array.from({ length: BURST_COUNT }, () => first + random() * (last - first))
  const generated = Array.from({ length: DENSE_COUNT }, (_, index) => {
    const inBurst = random() < BURST_SHARE
    const centre = centres[Math.floor(random() * BURST_COUNT)]!
    const jitter = (random() + random() + random() - 1.5) * BURST_SPREAD_MS
    const time = Math.round(Math.min(last, Math.max(first, inBurst ? centre + jitter : first + random() * (last - first))))
    const lane = pickLane(random())
    const process = processes[Math.floor(random() * processes.length)]!
    const api = API_CALLS[Math.floor(random() * API_CALLS.length)]!
    return { time, lane, process, api, index }
  })
  const alerts = sample.filter((event) => event.kind === 'alert')
  return [
    ...generated
      .sort((a, b) => a.time - b.time || a.index - b.index)
      .map(({ time, lane, process, api, index }, position): Event => ({
        id: `dense-${position + 1}`,
        time: new Date(time).toISOString(),
        sequence: position + 1,
        lane,
        kind: 'event',
        category: [lane],
        action: LANE_ACTIONS[lane],
        module: 'capemon',
        dataset: `capemon.${lane}`,
        summary: summaryOf(lane, api, process.name ?? 'unknown.exe', index),
        severity: null,
        process,
        api_name: lane === 'api' ? api : null,
        rule_name: null,
        rule_ruleset: null,
        destination: lane === 'network' ? { ip: `192.168.150.${(index % 200) + 1}`, port: 443, domain: null } : null,
        dns_query: null,
        url: null,
        file_path: lane === 'file' ? `C:\\Users\\anna\\AppData\\Local\\Temp\\tmp${index}.dat` : null,
        registry_path: lane === 'registry' ? `HKCU\\Software\\Vendor\\Key${index % 40}` : null,
        fields: {},
      })),
    ...alerts,
  ].sort((a, b) => Date.parse(a.time) - Date.parse(b.time) || (a.sequence ?? 0) - (b.sequence ?? 0))
}

const CLOSE_RUN_START = Date.parse('2026-10-13T15:40:10.000Z')
// [milliseconds after the start, lane]: three at one instant, a burst of API calls, a lane of its own at 8 ms.
const CLOSE_RUN: [number, Lane][] = [
  [0, 'process'],
  [1, 'file'],
  [1, 'file'],
  [1, 'file'],
  [2, 'api'],
  [3, 'api'],
  [3, 'api'],
  [3, 'api'],
  [3, 'api'],
  [3, 'api'],
  [4, 'registry'],
  [6, 'network'],
  [8, 'memory'],
  [9, 'api'],
]

/** Events a few milliseconds apart, for the deepest zoom: some at the very same instant, one run of API calls. */
export function closeEvents(sample: Event[]): Event[] {
  const process = sample.find((event) => event.process?.pid)!.process!
  const run = CLOSE_RUN.map(([offset, lane], index): Event => ({
    ...sample[0]!,
    id: `close-${index + 1}`,
    time: new Date(CLOSE_RUN_START + offset).toISOString(),
    sequence: index + 1,
    lane,
    kind: 'event',
    category: [lane],
    action: LANE_ACTIONS[lane],
    summary: `${process.name} ${LANE_ACTIONS[lane]} #${index + 1}`,
    severity: null,
    process,
    api_name: lane === 'api' ? API_CALLS[index % API_CALLS.length]! : null,
    rule_name: null,
    rule_ruleset: null,
    fields: {},
  }))
  const alert = sample.find((event) => event.kind === 'alert')!
  return [{ ...alert, id: 'close-alert', time: new Date(CLOSE_RUN_START + 5).toISOString(), sequence: 99 }, ...run].sort(
    (a, b) => Date.parse(a.time) - Date.parse(b.time) || (a.sequence ?? 0) - (b.sequence ?? 0),
  )
}

/** The stored document of an event that has no hand-written one: the few fields the search mock filters and shows. */
export function syntheticSource(event: Event): Record<string, unknown> {
  return {
    '@timestamp': event.time,
    event: { id: event.id, sequence: event.sequence, kind: event.kind, action: event.action, module: event.module, dataset: event.dataset },
    tartarus: { lane: event.lane, summary: event.summary, raw: { note: 'generated record' } },
    process: { pid: event.process?.pid, name: event.process?.name, entity_id: event.process?.entity_id },
    ...(event.api_name && { api: { name: event.api_name } }),
    ...(event.file_path && { file: { path: event.file_path } }),
    ...(event.registry_path && { registry: { path: event.registry_path } }),
  }
}

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
// The backend's own list of histogram steps (backend spec, "Events API (as built)").
const STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500, SECOND, 2 * SECOND, 5 * SECOND, 10 * SECOND, 15 * SECOND, 30 * SECOND, MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE, HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY]
const AUTO_BUCKETS = 120
const MAX_BUCKETS = 2000
const MAX_DETECTIONS = 500

function bucketCount(from: number, to: number, step: number): number {
  return Math.floor(to / step) - Math.floor(from / step) + 1
}

function stepFor(from: number, to: number, interval: number | 'auto'): number {
  if (interval === 'auto') return STEPS.find((step) => bucketCount(from, to, step) <= AUTO_BUCKETS) ?? STEPS[STEPS.length - 1]!
  let step = Math.max(1, interval)
  while (bucketCount(from, to, step) > MAX_BUCKETS) step *= 2
  return step
}

/** What the backend's histogram answers for the events a filter matched: the span, contiguous epoch-aligned buckets by lane, and the alerts. */
export function histogramOf(matched: Event[], range: TimeRange | null | undefined, interval: HistogramRequest['interval'] = 'auto'): Histogram {
  const times = matched.map((event) => Date.parse(event.time))
  const from = range?.from ? Date.parse(range.from) : times.length > 0 ? Math.min(...times) : undefined
  const to = range?.to ? Date.parse(range.to) : times.length > 0 ? Math.max(...times) : undefined
  if (from === undefined || to === undefined) return { interval_ms: SECOND, from: null, to: null, total: 0, buckets: [], detections: [] }
  const step = stepFor(from, to, interval)
  const buckets = new Map<number, Record<string, number>>()
  for (let start = Math.floor(from / step) * step; start <= to; start += step) buckets.set(start, {})
  for (const event of matched) {
    const byLane = buckets.get(Math.floor(Date.parse(event.time) / step) * step)
    if (byLane) byLane[event.lane ?? 'unknown'] = (byLane[event.lane ?? 'unknown'] ?? 0) + 1
  }
  return {
    interval_ms: step,
    from: new Date(from).toISOString(),
    to: new Date(to).toISOString(),
    total: matched.length,
    buckets: [...buckets].map(([start, by_lane]) => ({ time: new Date(start).toISOString(), total: Object.values(by_lane).reduce((sum, count) => sum + count, 0), by_lane })),
    detections: matched
      .filter((event) => event.kind === 'alert')
      .slice(0, MAX_DETECTIONS)
      .map((event) => ({ time: event.time, id: event.id, name: event.rule_name, severity: event.severity, ruleset: event.rule_ruleset })),
  }
}
