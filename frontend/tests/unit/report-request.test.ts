import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobRead } from '@/api'

vi.mock('@/api', () => ({ exportReport: vi.fn() }))

const { exportReport } = await import('@/api')
const {
  DEFAULT_REPORT_INCLUDE,
  REPORT_FORMATS,
  REPORT_OPTIONS,
  reportBlockReason,
  requestReport,
} = await import('@/services/report-request')

const JOB: JobRead = {
  id: 7,
  type: 'export_report',
  analysis_id: 193,
  status: 'pending',
  step: 'Queued',
  progress: 0,
  result: null,
  log: '',
  created_at: '2026-10-15T10:00:00Z',
  updated_at: '2026-10-15T10:00:00Z',
}

function reply(value: { data?: JobRead; error?: unknown }) {
  vi.mocked(exportReport).mockResolvedValue(value as never)
}

beforeEach(() => {
  vi.mocked(exportReport).mockReset()
})

describe('report options', () => {
  it('offers HTML and PDF', () => {
    expect(REPORT_FORMATS.map((format) => format.value)).toEqual(['html', 'pdf'])
  })

  it('includes everything by default', () => {
    expect(DEFAULT_REPORT_INCLUDE).toEqual({ notes: true, screenshots: true, raw_iocs: true })
  })

  it('explains each include option in one line', () => {
    expect(REPORT_OPTIONS.map((option) => option.key)).toEqual(['notes', 'screenshots', 'raw_iocs'])
    for (const option of REPORT_OPTIONS) {
      expect(option.hint).not.toContain('\n')
      expect(option.hint.length).toBeGreaterThan(10)
    }
    expect(REPORT_OPTIONS.find((option) => option.key === 'raw_iocs')?.hint).toContain('first five')
  })
})

describe('reportBlockReason', () => {
  it('lets a finished analysis be reported', () => {
    expect(reportBlockReason('done')).toBeUndefined()
  })

  it.each(['queued', 'starting', 'running', 'processing', 'ingesting', 'failed', 'report_failed', 'cancelled'] as const)(
    'explains why a %s analysis cannot',
    (status) => {
      expect(reportBlockReason(status)).toBe('Reports are built from a finished analysis')
    },
  )
})

describe('requestReport', () => {
  it('posts the format and the include options for the analysis and returns the job', async () => {
    reply({ data: JOB })

    const outcome = await requestReport(193, 'pdf', { notes: true, screenshots: false, raw_iocs: false })

    expect(outcome).toEqual({ job: JOB })
    expect(exportReport).toHaveBeenCalledWith({
      path: { analysis_id: 193 },
      body: { format: 'pdf', include: { notes: true, screenshots: false, raw_iocs: false } },
      meta: { quietStatuses: [404, 409, 422] },
    })
  })

  it('returns the message of a 409 for the dialog to show inline', async () => {
    reply({ error: { error: { code: 'conflict', message: 'Analysis 193 is not finished yet', details: {} } } })
    expect(await requestReport(193, 'html', DEFAULT_REPORT_INCLUDE)).toEqual({
      message: 'Analysis 193 is not finished yet',
    })
  })

  it('prefers the first field message of a 422', async () => {
    reply({
      error: {
        error: {
          code: 'validation_error',
          message: 'Request validation failed',
          details: { fields: [{ location: ['body', 'format'], message: "Input should be 'html' or 'pdf'" }] },
        },
      },
    })
    expect(await requestReport(193, 'html', DEFAULT_REPORT_INCLUDE)).toEqual({
      message: "Input should be 'html' or 'pdf'",
    })
  })

  it('falls back to a generic message when the failure carried none', async () => {
    reply({ error: 'bad gateway' })
    const outcome = await requestReport(193, 'html', DEFAULT_REPORT_INCLUDE)
    expect(outcome).toEqual({ message: 'Something went wrong talking to the backend.' })
  })
})
