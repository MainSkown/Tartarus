import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'
import { analysesCancel, analysesCreate, analysesDelete, analysesList, analysesRead } from '@/api'
import type { AnalysesListData, AnalysisRead, Route } from '@/api'
import { errorMessage } from '@/services/api-error'
import { isTerminalStatus } from '@/services/analysis-status'
import { NOT_FOUND_STATUS, quietOn } from '@/services/quiet-statuses'
import { validationIssues, type ValidationIssue } from '@/services/validation-errors'

const POLL_INTERVAL_MS = 2_000
const BACKOFF_INTERVAL_MS = 10_000
const FAILURES_BEFORE_BACKOFF = 3

export type AnalysisListQuery = NonNullable<AnalysesListData['query']>

export interface SubmitOptions {
  route: Route
  timeout: number
  package?: string
}

/** Thrown by `submit` when the backend refuses the upload; `issues` holds a 422's per-field messages. */
export class SubmissionRejected extends Error {
  readonly issues: ValidationIssue[]

  constructor(message: string, issues: ValidationIssue[]) {
    super(message)
    this.name = 'SubmissionRejected'
    this.issues = issues
  }
}

interface LoadFailure {
  message: string
  status?: number
}

function failureOf(error: unknown, response?: Response): LoadFailure {
  return { message: errorMessage(error), status: response?.status }
}

function isPending(analysis: AnalysisRead): boolean {
  return !isTerminalStatus(analysis.status)
}

/**
 * The analyses the Dashboard lists and the one the analysis page shows. While any of them is
 * queued or running, `startPolling` keeps them fresh (decision 4 of the M1a plan: polling, not
 * the live feed); it stops by itself once nothing is pending and re-arms when a fetch or a
 * submit brings pending work back.
 */
export const useAnalysesStore = defineStore('analyses', () => {
  const items = ref<AnalysisRead[]>([])
  const total = ref(0)
  const current = ref<AnalysisRead>()
  const loadError = ref<string>()
  const loadErrorStatus = ref<number>()
  const activeFetches = ref(0)
  const loading = computed(() => activeFetches.value > 0)

  let listQuery: AnalysisListQuery | undefined
  // A response is applied only while it is the latest request of its kind, so a slow poll can
  // never overwrite what a newer fetch (or a removal) already settled.
  let listRequestId = 0
  let currentRequestId = 0

  let pollingRequested = false
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let pollInFlight = false
  let consecutivePollFailures = 0

  /** Resolves to the failure, or `undefined` when the list was loaded or superseded. */
  async function loadList(): Promise<LoadFailure | undefined> {
    const requestId = ++listRequestId
    const { data, error, response } = await analysesList({ query: listQuery ?? {} })
    if (requestId !== listRequestId) return undefined
    if (error || !data) return failureOf(error, response)
    items.value = data.items
    total.value = data.total
    return undefined
  }

  async function loadCurrent(id: number): Promise<LoadFailure | undefined> {
    const requestId = ++currentRequestId
    // A missing analysis is a state the page shows, not a fault to toast about.
    const { data, error, response } = await analysesRead({
      path: { analysis_id: id },
      meta: quietOn(NOT_FOUND_STATUS),
    })
    if (requestId !== currentRequestId) return undefined
    if (error || !data) return failureOf(error, response)
    current.value = data
    return undefined
  }

  async function trackFetch(load: () => Promise<LoadFailure | undefined>): Promise<void> {
    activeFetches.value++
    try {
      const failure = await load()
      loadError.value = failure?.message
      loadErrorStatus.value = failure?.status
    } finally {
      activeFetches.value--
    }
    schedulePoll()
  }

  function fetchList(query: AnalysisListQuery = {}): Promise<void> {
    listQuery = query
    return trackFetch(loadList)
  }

  function fetchOne(id: number): Promise<void> {
    if (current.value?.id !== id) current.value = undefined
    return trackFetch(() => loadCurrent(id))
  }

  async function submit(file: File, options: SubmitOptions): Promise<AnalysisRead> {
    const { data, error } = await analysesCreate({ body: { file, options: JSON.stringify(options) } })
    if (error || !data) throw new SubmissionRejected(errorMessage(error), validationIssues(error))
    if (listQuery) await loadList()
    startPolling()
    return data
  }

  function replaceEverywhere(updated: AnalysisRead): void {
    items.value = items.value.map((item) => (item.id === updated.id ? updated : item))
    if (current.value?.id === updated.id) current.value = updated
  }

  async function cancel(id: number): Promise<boolean> {
    const { data, error } = await analysesCancel({ path: { analysis_id: id } })
    if (error || !data) return false
    replaceEverywhere(data)
    return true
  }

  async function remove(id: number): Promise<boolean> {
    const { error } = await analysesDelete({ path: { analysis_id: id } })
    if (error) return false
    listRequestId++
    currentRequestId++
    if (items.value.some((item) => item.id === id)) total.value = Math.max(0, total.value - 1)
    items.value = items.value.filter((item) => item.id !== id)
    if (current.value?.id === id) current.value = undefined
    return true
  }

  function listNeedsPolling(): boolean {
    return items.value.some(isPending)
  }

  function currentNeedsPolling(): boolean {
    return current.value !== undefined && isPending(current.value)
  }

  function nextPollDelayMs(): number {
    return consecutivePollFailures >= FAILURES_BEFORE_BACKOFF ? BACKOFF_INTERVAL_MS : POLL_INTERVAL_MS
  }

  // Chaining each poll off the end of the previous one (instead of a setInterval) is what
  // keeps a slow response from piling up requests behind it.
  function schedulePoll(): void {
    const idle = pollTimer === undefined && !pollInFlight
    if (!pollingRequested || !idle || !(listNeedsPolling() || currentNeedsPolling())) return
    pollTimer = setTimeout(() => void poll(), nextPollDelayMs())
  }

  async function poll(): Promise<void> {
    pollTimer = undefined
    pollInFlight = true
    try {
      const loads: Promise<LoadFailure | undefined>[] = []
      if (listNeedsPolling()) loads.push(loadList())
      if (current.value && currentNeedsPolling()) loads.push(loadCurrent(current.value.id))
      const failures = (await Promise.all(loads)).filter((failure) => failure !== undefined)
      consecutivePollFailures = failures.length > 0 ? consecutivePollFailures + 1 : 0
    } finally {
      pollInFlight = false
    }
    schedulePoll()
  }

  function startPolling(): void {
    pollingRequested = true
    schedulePoll()
  }

  function stopPolling(): void {
    pollingRequested = false
    consecutivePollFailures = 0
    clearTimeout(pollTimer)
    pollTimer = undefined
  }

  onScopeDispose(stopPolling)

  return {
    items,
    total,
    current,
    loading,
    loadError,
    loadErrorStatus,
    fetchList,
    fetchOne,
    submit,
    cancel,
    remove,
    startPolling,
    stopPolling,
  }
})
