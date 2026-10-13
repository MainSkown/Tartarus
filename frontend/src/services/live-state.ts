import type { AnalysisStatus } from '@/api'
import { isTerminalStatus } from '@/services/analysis-status'
import type { LiveError, LiveEvent, LiveProcessNode, LiveSubscription, ProcessDelta } from '@/services/live-messages'

const API_LANE = 'api'
const RATE_WINDOW_MS = 30_000
// A stream that has only just begun is averaged over this much time, so one early batch is not read as a flood.
const MIN_RATE_SPAN_MS = 5_000
const MS_PER_MINUTE = 60_000

/** The user's choice of lanes and processes; an empty list means "all". */
export interface LiveFilter {
  lanes: string[]
  pids: number[]
  includeApi: boolean
}

export const NO_FILTER: LiveFilter = { lanes: [], pids: [], includeApi: false }

/** What to send as `subscribe`. An empty list is left out: the server reads one as "match nothing". */
export function subscriptionOf(filter: LiveFilter): LiveSubscription {
  const subscription: LiveSubscription = { include_api: filter.includeApi }
  if (filter.lanes.length > 0) {
    // The server applies the lane list before include_api, so showing API calls beside a lane choice means naming the lane.
    subscription.lanes = filter.includeApi ? [...filter.lanes, API_LANE] : filter.lanes
  }
  if (filter.pids.length > 0) subscription.pids = filter.pids
  return subscription
}

/** The server's own matching rule, so events already buffered can be re-filtered without a round trip. */
export function matchesSubscription(event: LiveEvent, subscription: LiveSubscription): boolean {
  const { lane } = event.tartarus
  const namesApi = subscription.lanes?.includes(API_LANE) ?? false
  if (lane === API_LANE && !subscription.include_api && !namesApi) return false
  if (subscription.lanes && !subscription.lanes.includes(lane)) return false
  if (!subscription.pids) return true
  const pid = event.process?.pid
  return pid !== undefined && subscription.pids.includes(pid)
}

export function applyProcessDelta(
  processes: ReadonlyMap<number, LiveProcessNode>,
  delta: ProcessDelta,
): Map<number, LiveProcessNode> {
  return new Map(processes).set(delta.node.pid, delta.node)
}

export interface ProcessTreeNode {
  process: LiveProcessNode
  children: ProcessTreeNode[]
}

export interface TreeRow {
  process: LiveProcessNode
  depth: number
}

function byStartThenPid(a: LiveProcessNode, b: LiveProcessNode): number {
  if (a.start !== b.start) {
    if (a.start === null) return 1
    if (b.start === null) return -1
    return a.start < b.start ? -1 : 1
  }
  return a.pid - b.pid
}

/** Processes under the parent they name, the ones with no known parent as roots. A parent cycle is unreachable and left out. */
export function processRoots(processes: ReadonlyMap<number, LiveProcessNode>): ProcessTreeNode[] {
  const childrenOf = new Map<number, LiveProcessNode[]>()
  const roots: LiveProcessNode[] = []
  for (const process of processes.values()) {
    const isRoot = process.ppid === null || process.ppid === process.pid || !processes.has(process.ppid)
    if (isRoot) roots.push(process)
    else childrenOf.set(process.ppid!, [...(childrenOf.get(process.ppid!) ?? []), process])
  }
  const build = (process: LiveProcessNode): ProcessTreeNode => ({
    process,
    children: (childrenOf.get(process.pid) ?? []).sort(byStartThenPid).map(build),
  })
  return roots.sort(byStartThenPid).map(build)
}

export function treeRows(roots: ProcessTreeNode[], depth = 0): TreeRow[] {
  return roots.flatMap((node) => [{ process: node.process, depth }, ...treeRows(node.children, depth + 1)])
}

export function appendBounded(
  buffer: readonly LiveEvent[],
  incoming: readonly LiveEvent[],
  limit: number,
): { events: LiveEvent[]; trimmed: number } {
  const all = [...buffer, ...incoming]
  const trimmed = Math.max(0, all.length - limit)
  return { events: trimmed > 0 ? all.slice(trimmed) : all, trimmed }
}

export interface RateSample {
  at: number
  count: number
}

export function eventsPerMinute(samples: readonly RateSample[], now: number): number {
  const recent = samples.filter((sample) => sample.at >= now - RATE_WINDOW_MS)
  if (recent.length === 0) return 0
  const total = recent.reduce((sum, sample) => sum + sample.count, 0)
  const span = Math.min(RATE_WINDOW_MS, Math.max(MIN_RATE_SPAN_MS, now - recent[0]!.at))
  return Math.round((total * MS_PER_MINUTE) / span)
}

export interface StreamContext {
  status: AnalysisStatus
  processCount: number
  queuePosition: number | null
  filtered: boolean
}

/** Why the stream has nothing to show, in the order the run goes: queued, guest starting, connected, over. */
export function streamEmptyMessage({ status, processCount, queuePosition, filtered }: StreamContext): string {
  if (status === 'queued') return queuePosition === null ? 'queued, waiting for the guest' : `queued, position ${queuePosition}`
  if (filtered) return 'no events match the filter'
  if (isTerminalStatus(status)) return 'the run is over; this view shows only what it streamed while open, see the other tabs'
  if (processCount === 0) return 'starting the guest...'
  return 'connected, no events yet'
}

export function processesEmptyMessage({ status, queuePosition }: Pick<StreamContext, 'status' | 'queuePosition'>): string {
  if (status === 'queued') return streamEmptyMessage({ status, processCount: 0, queuePosition, filtered: false })
  return isTerminalStatus(status) ? 'the run is over; this view saw no process, see the PROCESSES tab' : 'starting the guest...'
}

const FINAL_REPORT_UNAFFECTED = 'the final report is not affected'

export function describeLiveError({ code, message }: LiveError): string {
  if (code === 'live_index_failed') return `live indexing failed (${message}); ${FINAL_REPORT_UNAFFECTED}`
  if (code === 'log_format') return `a log record could not be read (${message}); ${FINAL_REPORT_UNAFFECTED}`
  return `${code}: ${message}`
}
