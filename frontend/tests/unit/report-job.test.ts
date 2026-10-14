import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobProgress } from '@/api'

vi.mock('@/api', () => ({ jobsDownload: vi.fn() }))
vi.mock('@/services/download', () => ({ saveDownload: vi.fn() }))

const { jobsDownload } = await import('@/api')
const { saveDownload } = await import('@/services/download')
const { downloadReportFile, jobFailureReason, jobFilename } = await import('@/services/report-job')

function job(overrides: Partial<JobProgress> = {}): JobProgress {
  return {
    id: 7,
    type: 'export_report',
    analysis_id: 193,
    status: 'done',
    step: 'Saving the file',
    progress: 100,
    result: { file: '193/tartarus-report-193.pdf', filename: 'tartarus-report-193.pdf', media_type: 'application/pdf' },
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(jobsDownload).mockReset().mockResolvedValue({ data: new Blob() } as never)
  vi.mocked(saveDownload).mockReset().mockResolvedValue(true)
})

describe('jobFilename', () => {
  it('is the name the job result gives its file', () => {
    expect(jobFilename(job())).toBe('tartarus-report-193.pdf')
  })

  it('is undefined while the job has produced no file', () => {
    expect(jobFilename(job({ result: null }))).toBeUndefined()
    expect(jobFilename(job({ result: { filename: 42 } }))).toBeUndefined()
  })
})

describe('jobFailureReason', () => {
  it('is the error the job result carries', () => {
    expect(jobFailureReason(job({ status: 'failed', result: { error: 'WeasyPrint ran out of memory' } }))).toBe(
      'WeasyPrint ran out of memory',
    )
  })

  it('says the backend restarted for an interrupted job', () => {
    expect(jobFailureReason(job({ status: 'interrupted', result: null }))).toBe(
      'The backend restarted while the report was being built',
    )
  })

  it('has a generic reason for a failed job that named none', () => {
    expect(jobFailureReason(job({ status: 'failed', result: null }))).toBe('The report could not be built')
  })
})

describe('downloadReportFile', () => {
  it('asks for the job file as a blob and saves it under the job file name', async () => {
    const saved = await downloadReportFile(job())

    expect(saved).toBe(true)
    expect(jobsDownload).toHaveBeenCalledWith({ path: { job_id: 7 }, parseAs: 'blob' })
    expect(saveDownload).toHaveBeenCalledWith(expect.any(Promise), 'tartarus-report-193.pdf')
  })

  it('falls back to a name built from the job when the result names none', async () => {
    await downloadReportFile(job({ result: null }))
    expect(saveDownload).toHaveBeenCalledWith(expect.any(Promise), 'tartarus-report-193')
  })
})
