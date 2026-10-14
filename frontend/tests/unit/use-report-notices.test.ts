import { createPinia, setActivePinia } from 'pinia'
import { Notify } from 'quasar'
import { effectScope, reactive, type EffectScope } from 'vue'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import type { JobProgress } from '@/api'

vi.mock('@/api', () => ({ exportReport: vi.fn(), jobsRead: vi.fn() }))
vi.mock('@/services/report-job', async (importOriginal: () => Promise<Record<string, unknown>>) => ({
  ...(await importOriginal()),
  downloadReportFile: vi.fn(),
}))

const system = reactive({ connectionState: 'open', onJob: vi.fn() })
let pushJob: (job: JobProgress) => void = () => undefined
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))

const { downloadReportFile } = await import('@/services/report-job')
const { useJobsStore } = await import('@/stores/jobs')
const { useReportNotices } = await import('@/composables/use-report-notices')

function job(overrides: Partial<JobProgress> = {}): JobProgress {
  return {
    id: 7,
    type: 'export_report',
    analysis_id: 193,
    status: 'running',
    step: 'Rendering the PDF',
    progress: 50,
    result: null,
    ...overrides,
  }
}

const DONE = job({ status: 'done', progress: 100, result: { filename: 'tartarus-report-193.pdf' } })

let scope: EffectScope

beforeEach(() => {
  vi.clearAllMocks()
  Notify.create = vi.fn()
  system.onJob.mockReset().mockImplementation((handler: (job: JobProgress) => void) => {
    pushJob = handler
    return () => undefined
  })
  setActivePinia(createPinia())
  scope = effectScope()
  scope.run(() => {
    useJobsStore()
    useReportNotices()
  })
})

afterEach(() => scope.stop())

describe('useReportNotices', () => {
  it('toasts "Report ready" with a download action when a report finishes while no dialog is open', () => {
    pushJob(job())
    pushJob(DONE)

    expect(Notify.create).toHaveBeenCalledTimes(1)
    const options = vi.mocked(Notify.create).mock.calls[0]![0] as { type: string; message: string; caption: string; actions: { label?: string; handler?: () => void }[] }
    expect(options).toMatchObject({ type: 'tt-success', message: 'Report ready', caption: '#193 · tartarus-report-193.pdf' })
    const download = options.actions.find((action) => action.label === 'DOWNLOAD')!
    download.handler!()
    expect(downloadReportFile).toHaveBeenCalledWith(DONE)
  })

  it('stays silent while the report dialog of that analysis is open', () => {
    useJobsStore().viewing = 193
    pushJob(job())
    pushJob(DONE)
    expect(Notify.create).not.toHaveBeenCalled()
  })

  it('still toasts when the open dialog belongs to another analysis', () => {
    useJobsStore().viewing = 200
    pushJob(job())
    pushJob(DONE)
    expect(Notify.create).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['failed', { error: 'WeasyPrint ran out of memory' }, 'WeasyPrint ran out of memory'],
    ['interrupted', null, 'The backend restarted while the report was being built'],
  ] as const)('toasts an error with the reason when a report %s', (status, result, reason) => {
    pushJob(job())
    pushJob(job({ status, result }))
    expect(Notify.create).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tt-error', message: 'Report failed', caption: `#193 · ${reason}` }),
    )
  })
})
