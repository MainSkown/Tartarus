import type { JobProgress } from '@/api'
import { isFinishedJob } from '@/services/job-status'

export type ReportView = 'form' | 'progress' | 'done' | 'failed'

/** What the report dialog shows: the form until a job exists, then the job's progress or outcome. `composing` returns to the form for a new report. */
export function reportView(job: JobProgress | undefined, composing: boolean): ReportView {
  if (job === undefined || composing) return 'form'
  if (job.status === 'done') return 'done'
  return isFinishedJob(job.status) ? 'failed' : 'progress'
}
