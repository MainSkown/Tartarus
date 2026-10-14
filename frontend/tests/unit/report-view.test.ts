import { describe, expect, it } from 'vitest'
import type { JobProgress, JobStatus } from '@/api'
import { jobFormat } from '@/services/report-job'
import { reportView } from '@/services/report-view'

function job(status: JobStatus, result: JobProgress['result'] = null): JobProgress {
  return { id: 7, type: 'export_report', analysis_id: 193, status, step: '', progress: 0, result }
}

describe('reportView', () => {
  it('is the form when there is no job, or when the analyst asked for a new report', () => {
    expect(reportView(undefined, false)).toBe('form')
    expect(reportView(job('done'), true)).toBe('form')
    expect(reportView(job('running'), true)).toBe('form')
  })

  it.each(['pending', 'running'] as const)('shows progress for a %s job', (status) => {
    expect(reportView(job(status), false)).toBe('progress')
  })

  it('shows the download for a done job', () => {
    expect(reportView(job('done'), false)).toBe('done')
  })

  it.each(['failed', 'interrupted'] as const)('shows the failure of a %s job', (status) => {
    expect(reportView(job(status), false)).toBe('failed')
  })
})

describe('jobFormat', () => {
  it('reads the format of the built file from its name', () => {
    expect(jobFormat(job('done', { filename: 'tartarus-report-193.pdf' }))).toBe('pdf')
    expect(jobFormat(job('done', { filename: 'report.HTML' }))).toBe('html')
  })

  it('is undefined without a file name or with another extension', () => {
    expect(jobFormat(job('running'))).toBeUndefined()
    expect(jobFormat(job('done', { filename: 'report.zip' }))).toBeUndefined()
  })
})
