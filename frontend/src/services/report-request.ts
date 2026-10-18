import { exportReport } from '@/api'
import type { AnalysisStatus, JobRead, ReportInclude, ReportVariant } from '@/api'
import { t, type MessageKey } from '@/i18n'
import { NOT_FOUND_STATUS, quietOn } from '@/services/quiet-statuses'
import { refusalMessage } from '@/services/validation-errors'

export type ReportSections = Required<ReportInclude>

export const REPORT_FORMATS: { value: ReportVariant; label: string }[] = [
  { value: 'html', label: 'HTML' },
  { value: 'pdf', label: 'PDF' },
]

export const DEFAULT_REPORT_INCLUDE: ReportSections = { notes: true, screenshots: true, raw_iocs: true }

export const REPORT_OPTIONS: { key: keyof ReportSections; labelKey: MessageKey; hintKey: MessageKey }[] = [
  { key: 'notes', labelKey: 'reports.option.notes.label', hintKey: 'reports.option.notes.hint' },
  { key: 'screenshots', labelKey: 'reports.option.screenshots.label', hintKey: 'reports.option.screenshots.hint' },
  { key: 'raw_iocs', labelKey: 'reports.option.rawIocs.label', hintKey: 'reports.option.rawIocs.hint' },
]

const CONFLICT_STATUS = 409
const UNPROCESSABLE_STATUS = 422

export function reportBlockReason(status: AnalysisStatus): string | undefined {
  return status === 'done' ? undefined : t('reports.blocked.notFinished')
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
