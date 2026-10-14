import { createPinia, setActivePinia } from 'pinia'
import { nextTick, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobProgress, JobRead } from '@/api'

vi.mock('@/api', () => ({ exportReport: vi.fn(), jobsRead: vi.fn() }))

const system = reactive({
  connectionState: 'open' as string,
  onJob: vi.fn(),
})
let pushJob: (job: JobProgress) => void = () => undefined
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))

const { exportReport, jobsRead } = await import('@/api')
const { useJobsStore } = await import('@/stores/jobs')
const { DEFAULT_REPORT_INCLUDE } = await import('@/services/report-request')

function progress(overrides: Partial<JobProgress> = {}): JobProgress {
  return {
    id: 7,
    type: 'export_report',
    analysis_id: 193,
    status: 'running',
    step: 'Reading the analysis files',
    progress: 4,
    result: null,
    ...overrides,
  }
}

function read(overrides: Partial<JobProgress> = {}): JobRead {
  return { ...progress(overrides), log: '', created_at: '2026-10-15T10:00:00Z', updated_at: '2026-10-15T10:00:00Z' }
}

function accepted(job: JobRead): void {
  vi.mocked(exportReport).mockResolvedValue({ data: job } as never)
}

function polled(job: JobRead): void {
  vi.mocked(jobsRead).mockResolvedValue({ data: job } as never)
}

let created: ReturnType<typeof useJobsStore> | undefined

function freshStore() {
  setActivePinia(createPinia())
  created = useJobsStore()
  return created
}

beforeEach(() => {
  vi.mocked(exportReport).mockReset()
  vi.mocked(jobsRead).mockReset()
  system.connectionState = 'open'
  system.onJob.mockReset().mockImplementation((handler: (job: JobProgress) => void) => {
    pushJob = handler
    return () => undefined
  })
})

afterEach(() => {
  created?.$dispose()
  created = undefined
  vi.useRealTimers()
})

describe('starting a report', () => {
  it('tracks the accepted job as the analysis latest report', async () => {
    accepted(read({ status: 'pending', step: 'Queued', progress: 0 }))
    const jobs = freshStore()

    const message = await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)

    expect(message).toBeUndefined()
    expect(jobs.reportFor(193)).toEqual(progress({ status: 'pending', step: 'Queued', progress: 0 }))
    expect(jobs.reportFor(194)).toBeUndefined()
  })

  it('returns the refusal and tracks nothing', async () => {
    vi.mocked(exportReport).mockResolvedValue({
      error: { error: { code: 'conflict', message: 'Analysis 193 is not finished yet', details: {} } },
    } as never)
    const jobs = freshStore()

    expect(await jobs.startReport(193, 'html', DEFAULT_REPORT_INCLUDE)).toBe('Analysis 193 is not finished yet')
    expect(jobs.reportFor(193)).toBeUndefined()
  })

  it('replaces the previous report of the analysis with the new one', async () => {
    const jobs = freshStore()
    accepted(read({ id: 7, status: 'done', progress: 100 }))
    await jobs.startReport(193, 'html', DEFAULT_REPORT_INCLUDE)
    accepted(read({ id: 8, status: 'pending', progress: 0 }))
    await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)

    expect(jobs.reportFor(193)?.id).toBe(8)
  })
})

describe('the request behind the latest report', () => {
  it('is remembered per analysis so a retry asks for the same thing', async () => {
    accepted(read({ status: 'pending', progress: 0 }))
    const jobs = freshStore()
    const include = { notes: false, screenshots: true, raw_iocs: false }

    await jobs.startReport(193, 'pdf', include)

    expect(jobs.requestFor(193)).toEqual({ format: 'pdf', include })
    expect(jobs.requestFor(194)).toBeUndefined()
  })

  it('is not replaced by a request the backend refused', async () => {
    const jobs = freshStore()
    accepted(read({ status: 'pending' }))
    await jobs.startReport(193, 'html', DEFAULT_REPORT_INCLUDE)
    vi.mocked(exportReport).mockResolvedValue({ error: { error: { message: 'no' } } } as never)

    await jobs.startReport(193, 'pdf', { notes: false, screenshots: false, raw_iocs: false })

    expect(jobs.requestFor(193)).toEqual({ format: 'html', include: DEFAULT_REPORT_INCLUDE })
  })
})

describe('job messages from the socket', () => {
  it('moves the tracked job along', async () => {
    accepted(read({ status: 'pending', progress: 0 }))
    const jobs = freshStore()
    await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)

    pushJob(progress({ step: 'Rendering the PDF', progress: 90 }))

    expect(jobs.reportFor(193)).toMatchObject({ status: 'running', step: 'Rendering the PDF', progress: 90 })
  })

  it('adopts a report job it did not start, such as one still active when the socket connected', () => {
    const jobs = freshStore()

    pushJob(progress({ id: 12, analysis_id: 200 }))

    expect(jobs.reportFor(200)?.id).toBe(12)
  })

  it('ignores jobs that are not reports and jobs of no analysis', () => {
    const jobs = freshStore()

    pushJob(progress({ type: 'ingest' }))
    pushJob(progress({ analysis_id: null }))

    expect(jobs.reportFor(193)).toBeUndefined()
  })

  it('does not let an older job replace the analysis latest report', async () => {
    const jobs = freshStore()
    pushJob(progress({ id: 9 }))

    pushJob(progress({ id: 7, status: 'done', progress: 100 }))

    expect(jobs.reportFor(193)?.id).toBe(9)
  })

  it('keeps a finished job finished when a late message says it is still running', async () => {
    accepted(read({ status: 'pending', progress: 0 }))
    const jobs = freshStore()
    pushJob(progress({ status: 'done', progress: 100, step: 'Saving the file' }))

    await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)

    expect(jobs.reportFor(193)?.status).toBe('done')
  })

  it.each(['done', 'failed', 'interrupted'] as const)('tells the finished handlers once when a job ends %s', (status) => {
    const jobs = freshStore()
    const finished: JobProgress[] = []
    jobs.onFinished((job) => finished.push(job))
    pushJob(progress())

    pushJob(progress({ status, progress: 100 }))
    pushJob(progress({ status, progress: 100 }))

    expect(finished).toHaveLength(1)
    expect(finished[0]).toMatchObject({ id: 7, status })
  })

  it('does not tell the finished handlers about a job still running, or after one unsubscribed', () => {
    const jobs = freshStore()
    const finished: JobProgress[] = []
    const unsubscribe = jobs.onFinished((job) => finished.push(job))

    pushJob(progress())
    expect(finished).toEqual([])

    unsubscribe()
    pushJob(progress({ status: 'done' }))
    expect(finished).toEqual([])
  })
})

describe('polling while the socket is down', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    system.connectionState = 'reconnecting'
  })

  it('reads the job every second until it finishes, then stops', async () => {
    accepted(read({ status: 'pending', progress: 0 }))
    const jobs = freshStore()
    await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)

    polled(read({ progress: 40, step: 'Rendering the PDF' }))
    await vi.advanceTimersByTimeAsync(1_000)
    expect(jobsRead).toHaveBeenCalledWith(expect.objectContaining({ path: { job_id: 7 } }))
    expect(jobs.reportFor(193)).toMatchObject({ progress: 40, step: 'Rendering the PDF' })

    polled(read({ status: 'done', progress: 100 }))
    await vi.advanceTimersByTimeAsync(1_000)
    expect(jobs.reportFor(193)?.status).toBe('done')

    vi.mocked(jobsRead).mockClear()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(jobsRead).not.toHaveBeenCalled()
  })

  it('does not poll while the socket is open', async () => {
    system.connectionState = 'open'
    accepted(read({ status: 'pending', progress: 0 }))
    const jobs = freshStore()
    await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)

    await vi.advanceTimersByTimeAsync(5_000)

    expect(jobsRead).not.toHaveBeenCalled()
  })

  it('starts polling when the socket drops under a running job and stops when it is back', async () => {
    system.connectionState = 'open'
    accepted(read())
    const jobs = freshStore()
    await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)
    polled(read({ progress: 50 }))

    system.connectionState = 'reconnecting'
    await nextTick()
    await vi.advanceTimersByTimeAsync(1_000)
    expect(jobsRead).toHaveBeenCalledTimes(1)

    system.connectionState = 'open'
    await nextTick()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(jobsRead).toHaveBeenCalledTimes(1)
    expect(jobs.reportFor(193)?.progress).toBe(50)
  })

  it('keeps polling through failed reads, slower after three in a row', async () => {
    accepted(read())
    const jobs = freshStore()
    await jobs.startReport(193, 'pdf', DEFAULT_REPORT_INCLUDE)
    vi.mocked(jobsRead).mockResolvedValue({ error: { error: { message: 'down' } } } as never)

    await vi.advanceTimersByTimeAsync(3_000)
    expect(jobsRead).toHaveBeenCalledTimes(3)

    await vi.advanceTimersByTimeAsync(4_000)
    expect(jobsRead).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(jobsRead).toHaveBeenCalledTimes(4)
    expect(jobs.reportFor(193)?.status).toBe('running')
  })
})
