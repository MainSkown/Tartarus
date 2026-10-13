import { computed, onScopeDispose, ref, shallowRef, watch, type Ref } from 'vue'
import type { AnalysisPhase } from '@/api'
import { isTerminalStatus } from '@/services/analysis-status'
import {
  parseLiveMessage,
  type LiveClientMessage,
  type LiveCounts,
  type LiveError,
  type LiveEvent,
  type LiveMessage,
  type LiveProcessNode,
  type LiveStatus,
} from '@/services/live-messages'
import {
  NO_FILTER,
  appendBounded,
  applyProcessDelta,
  eventsPerMinute as estimateEventsPerMinute,
  matchesSubscription,
  processRoots,
  subscriptionOf,
  type LiveFilter,
  type ProcessTreeNode,
  type RateSample,
} from '@/services/live-state'
import { ReconnectingWebSocketClient, type WsConnectionState } from '@/services/ws'

export const MAX_BUFFERED_EVENTS = 5000

const CLOSE_NORMAL = 1000
const CLOSE_NOT_FOUND = 4404
const RATE_SAMPLE_LIFETIME_MS = 60_000

export interface LiveStatusSnapshot extends LiveStatus {
  /** `Date.now()` when the server sent it, so a display can count on from the server's figures. */
  receivedAt: number
}

export interface LiveAnalysisOptions {
  webSocketFactory?: (url: string) => WebSocket
}

export interface LiveAnalysis {
  connection: Ref<WsConnectionState>
  notFound: Ref<boolean>
  status: Ref<LiveStatusSnapshot | undefined>
  phase: Ref<AnalysisPhase>
  finished: Ref<boolean>
  roots: Ref<ProcessTreeNode[]>
  processCount: Ref<number>
  /** What the list shows: the buffer through the filter, frozen while paused. */
  events: Ref<LiveEvent[]>
  received: Ref<number>
  trimmed: Ref<number>
  dropped: Ref<number>
  counts: Ref<LiveCounts | undefined>
  eventsPerMinute: Ref<number>
  errors: Ref<LiveError[]>
  filter: Ref<LiveFilter>
  paused: Ref<boolean>
  backlog: Ref<number>
  setFilter: (changes: Partial<LiveFilter>) => void
  pause: () => void
  resume: () => void
  clear: () => void
}

/**
 * The live feed of one analysis: owns the socket, reconnects it, and keeps the process tree, a
 * bounded buffer of the newest events and the counters that the LIVE tab renders. The socket is
 * closed when the calling scope ends.
 */
export function useLiveAnalysis(analysisId: number, options: LiveAnalysisOptions = {}): LiveAnalysis {
  const client = new ReconnectingWebSocketClient<LiveMessage>(
    `/ws/analyses/${analysisId}/live`,
    parseLiveMessage,
    options.webSocketFactory,
  )

  const notFound = ref(false)
  const status = ref<LiveStatusSnapshot>()
  const phase = ref<AnalysisPhase>('live')
  const processes = shallowRef<ReadonlyMap<number, LiveProcessNode>>(new Map())
  const buffer = shallowRef<readonly LiveEvent[]>([])
  const frozen = shallowRef<readonly LiveEvent[]>([])
  const received = ref(0)
  const trimmed = ref(0)
  const dropped = ref(0)
  const counts = ref<LiveCounts>()
  const eventsPerMinute = ref(0)
  const errors = ref<LiveError[]>([])
  const filter = ref<LiveFilter>(NO_FILTER)
  const paused = ref(false)
  const backlog = ref(0)
  let rateSamples: RateSample[] = []

  const finished = computed(() => status.value !== undefined && isTerminalStatus(status.value.status))
  const roots = computed(() => processRoots(processes.value))
  const processCount = computed(() => processes.value.size)
  const events = computed(() => {
    const subscription = subscriptionOf(filter.value)
    return (paused.value ? frozen.value : buffer.value).filter((event) => matchesSubscription(event, subscription))
  })

  function refreshRate(): void {
    const now = Date.now()
    rateSamples = rateSamples.filter((sample) => sample.at >= now - RATE_SAMPLE_LIFETIME_MS)
    eventsPerMinute.value = estimateEventsPerMinute(rateSamples, now)
  }

  function receiveEvents(incoming: LiveEvent[], skipped: number): void {
    dropped.value += skipped
    if (incoming.length === 0) return
    const result = appendBounded(buffer.value, incoming, MAX_BUFFERED_EVENTS)
    buffer.value = result.events
    trimmed.value += result.trimmed
    received.value += incoming.length
    if (paused.value) backlog.value += incoming.length
    rateSamples.push({ at: Date.now(), count: incoming.length })
    refreshRate()
  }

  function receiveError(error: LiveError): void {
    errors.value = [...errors.value.filter((known) => known.code !== error.code), error]
  }

  function receive(message: LiveMessage): void {
    switch (message.type) {
      case 'status':
        status.value = { ...message.data, receivedAt: Date.now() }
        phase.value = message.data.phase
        refreshRate()
        break
      case 'events':
        receiveEvents(message.data.events, message.data.dropped)
        break
      case 'process':
        processes.value = applyProcessDelta(processes.value, message.data)
        break
      case 'counts':
        counts.value = message.data
        break
      case 'phase':
        phase.value = message.data.phase
        break
      case 'error':
        receiveError(message.data)
        break
      case 'pong':
        break
    }
  }

  function send(message: LiveClientMessage): void {
    client.send(message)
  }

  function sendFilter(): void {
    send({ type: 'subscribe', data: subscriptionOf(filter.value) })
  }

  function setFilter(changes: Partial<LiveFilter>): void {
    filter.value = { ...filter.value, ...changes }
    sendFilter()
  }

  function pause(): void {
    if (paused.value) return
    frozen.value = buffer.value
    backlog.value = 0
    paused.value = true
  }

  function resume(): void {
    paused.value = false
    frozen.value = []
    backlog.value = 0
  }

  function clear(): void {
    buffer.value = []
    frozen.value = []
    trimmed.value = 0
    dropped.value = 0
    backlog.value = 0
  }

  client.subscribe(receive)
  client.onClose((code) => {
    if (code === CLOSE_NOT_FOUND) notFound.value = true
    // The server closes normally only after the last status, so there is nothing left to reconnect for.
    if (code === CLOSE_NORMAL || code === CLOSE_NOT_FOUND) client.disconnect()
  })
  watch(client.state, (state) => state === 'open' && sendFilter(), { flush: 'sync' })
  onScopeDispose(() => client.disconnect())
  client.connect()

  return {
    connection: client.state,
    notFound,
    status,
    phase,
    finished,
    roots,
    processCount,
    events,
    received,
    trimmed,
    dropped,
    counts,
    eventsPerMinute,
    errors,
    filter,
    paused,
    backlog,
    setFilter,
    pause,
    resume,
    clear,
  }
}
