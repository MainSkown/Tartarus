import { jobsDownload } from '@/api'
import type { JobProgress, ReportVariant } from '@/api'
import { t } from '@/i18n'
import { saveDownload } from '@/services/download'

export function jobFilename(job: JobProgress): string | undefined {
  const filename = job.result?.filename
  return typeof filename === 'string' ? filename : undefined
}

export function jobFormat(job: JobProgress): ReportVariant | undefined {
  const extension = jobFilename(job)?.split('.').pop()?.toLowerCase()
  return extension === 'html' || extension === 'pdf' ? extension : undefined
}

export function jobFailureReason(job: JobProgress): string {
  const error = job.result?.error
  if (typeof error === 'string') return error
  return job.status === 'interrupted' ? t('reports.job.interrupted') : t('reports.job.failed')
}

/** Saves the file of a finished report job; false when the download failed (the error toast has said why). */
export function downloadReportFile(job: JobProgress): Promise<boolean> {
  const fallbackName = `tartarus-report-${job.analysis_id}`
  return saveDownload(jobsDownload({ path: { job_id: job.id }, parseAs: 'blob' }), jobFilename(job) ?? fallbackName)
}
