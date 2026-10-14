import { defineStore } from 'pinia'
import { onScopeDispose, ref, watch } from 'vue'
import { jobsRead } from '@/api'
import type { JobProgress, JobRead, ReportVariant } from '@/api'
import { isFinishedJob } from '@/services/job-status'
import { quietOn } from '@/services/quiet-statuses'
import { requestReport, type ReportSections } from '@/services/report-request'
import { useSystemStore } from '@/stores/system'

const POLL_INTERVAL_MS = 1_000
const BACKOFF_INTERVAL_MS = 5_000
const FAILURES_BEFORE_BACKOFF = 3
const REPORT_JOB_TYPE = 'export_report'

type FinishedHandler = (job: JobProgress) => void

export interface ReportRequest {
  format: ReportVariant
  include: ReportSections
}

function progressOf(job: JobProgress | JobRead): JobProgress {
  const { id, type, analysis_id, status, step, progress, result } = job
  return { id, type, analysis_id, status, step, progress, result }
}

/**
 * The report jobs of this session, fed by the `job` pushes of the system socket. Only the latest
 * report of each analysis is shown, so the store keeps every job it has seen but points at one
 * per analysis. While the socket is down a running job is read from `GET /jobs/{id}` instead.
 */
export const useJobsStore = defineStore('jobs', () => {
  const system = useSystemStore()
  const jobs = ref<Record<number, JobProgress>>({})
  const latestReportIds = ref<Record<number, number>>({})
  const requests = ref<Record<number, ReportRequest>>({})
  /** The analysis whose report dialog is open, so a finished report is announced only when nobody is watching it. */
  const viewing = ref<number>()
  const finishedHandlers = new Set<FinishedHandler>()

  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let pollInFlight = false
  let consecutiveFailures = 0

  function reportFor(analysisId: number): JobProgress | undefined {
    const id = latestReportIds.value[analysisId]
    return id === undefined ? undefined : jobs.value[id]
  }

  function requestFor(analysisId: number): ReportRequest | undefined {
    return requests.value[analysisId]
  }

  function onFinished(handler: FinishedHandler): () => void {
    finishedHandlers.add(handler)
    return () => finishedHandlers.delete(handler)
  }

  function apply(incoming: JobProgress | JobRead): void {
    if (incoming.type !== REPORT_JOB_TYPE || incoming.analysis_id === null) return
    const held = jobs.value[incoming.id]
    const heldFinished = held !== undefined && isFinishedJob(held.status)
    // A message can overtake the response of the request that started the job.
    if (heldFinished && !isFinishedJob(incoming.status)) return
    const job = progressOf(incoming)
    jobs.value[job.id] = job
    const latest = latestReportIds.value[incoming.analysis_id]
    if (latest === undefined || job.id >= latest) latestReportIds.value[incoming.analysis_id] = job.id
    if (isFinishedJob(job.status) && !heldFinished) for (const handler of finishedHandlers) handler(job)
    schedulePoll()
  }

  /** Resolves to the refusal to show in the dialog, or `undefined` when the job was accepted. */
  async function startReport(
    analysisId: number,
    format: ReportVariant,
    include: ReportSections,
  ): Promise<string | undefined> {
    const outcome = await requestReport(analysisId, format, include)
    if ('message' in outcome) return outcome.message
    requests.value[analysisId] = { format, include }
    apply(outcome.job)
    return undefined
  }

  function runningJobs(): JobProgress[] {
    return Object.values(jobs.value).filter((job) => !isFinishedJob(job.status))
  }

  function nextPollDelayMs(): number {
    return consecutiveFailures >= FAILURES_BEFORE_BACKOFF ? BACKOFF_INTERVAL_MS : POLL_INTERVAL_MS
  }

  function schedulePoll(): void {
    const socketCarriesJobs = system.connectionState === 'open'
    if (socketCarriesJobs || pollTimer !== undefined || pollInFlight || runningJobs().length === 0) return
    pollTimer = setTimeout(() => void poll(), nextPollDelayMs())
  }

  async function poll(): Promise<void> {
    pollTimer = undefined
    pollInFlight = true
    try {
      const reads = await Promise.all(
        runningJobs().map((job) => jobsRead({ path: { job_id: job.id }, meta: quietOn(404, 500, 502, 503, 504) })),
      )
      const failed = reads.filter(({ data, error }) => error || !data)
      consecutiveFailures = failed.length > 0 ? consecutiveFailures + 1 : 0
      for (const { data } of reads) if (data) apply(data)
    } finally {
      pollInFlight = false
    }
    schedulePoll()
  }

  function stopPolling(): void {
    clearTimeout(pollTimer)
    pollTimer = undefined
  }

  const unsubscribe = system.onJob(apply)
  watch(
    () => system.connectionState,
    (state) => {
      if (state === 'open') stopPolling()
      else schedulePoll()
    },
  )

  onScopeDispose(() => {
    unsubscribe()
    stopPolling()
    finishedHandlers.clear()
  })

  return { viewing, reportFor, requestFor, startReport, onFinished }
})
