import { exportReport } from '@/api'
import type { AnalysisStatus, JobRead, ReportInclude, ReportVariant } from '@/api'
import { NOT_FOUND_STATUS, quietOn } from '@/services/quiet-statuses'
import { refusalMessage } from '@/services/validation-errors'

export type ReportSections = Required<ReportInclude>

export const REPORT_FORMATS: { value: ReportVariant; label: string }[] = [
  { value: 'html', label: 'HTML' },
  { value: 'pdf', label: 'PDF' },
]

export const DEFAULT_REPORT_INCLUDE: ReportSections = { notes: true, screenshots: true, raw_iocs: true }

export const REPORT_OPTIONS: { key: keyof ReportSections; label: string; hint: string }[] = [
  { key: 'notes', label: 'NOTES', hint: "Your notes on the analysis, its processes and its events. Tags always stay." },
  { key: 'screenshots', label: 'SCREENSHOTS', hint: 'The guest screenshots, embedded in the file. Off keeps it much smaller.' },
  { key: 'raw_iocs', label: 'RAW IOCS', hint: 'Every IOC of each type. Off lists only the first five per type.' },
]

const NOT_FINISHED_REASON = 'Reports are built from a finished analysis'
const CONFLICT_STATUS = 409
const UNPROCESSABLE_STATUS = 422

export function reportBlockReason(status: AnalysisStatus): string | undefined {
  return status === 'done' ? undefined : NOT_FINISHED_REASON
}

export type ReportRequestOutcome = { job: JobRead } | { message: string }

/** Starts the report job. A refusal comes back as a message for the dialog, not as a toast. */
export async function requestReport(
  analysisId: number,
  format: ReportVariant,
  include: ReportSections,
): Promise<ReportRequestOutcome> {
  const { data, error } = await exportReport({
    path: { analysis_id: analysisId },
    body: { format, include },
    meta: quietOn(NOT_FOUND_STATUS, CONFLICT_STATUS, UNPROCESSABLE_STATUS),
  })
  return error || !data ? { message: refusalMessage(error) } : { job: data }
}
