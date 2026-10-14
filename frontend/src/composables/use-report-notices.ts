import { onScopeDispose } from 'vue'
import { Notify } from 'quasar'
import type { JobProgress } from '@/api'
import { downloadReportFile, jobFailureReason, jobFilename } from '@/services/report-job'
import { useJobsStore } from '@/stores/jobs'

function announce(job: JobProgress): void {
  const caption = (detail: string | undefined) => `#${job.analysis_id} · ${detail}`
  if (job.status === 'done') {
    Notify.create({
      type: 'tt-success',
      message: 'Report ready',
      caption: caption(jobFilename(job)),
      actions: [{ label: 'DOWNLOAD', color: 'primary', handler: () => void downloadReportFile(job) }],
    })
  } else {
    Notify.create({ type: 'tt-error', message: 'Report failed', caption: caption(jobFailureReason(job)) })
  }
}

/** Announces a report that finishes while its dialog is closed; the open dialog shows the outcome itself. Mount once, in the app shell. */
export function useReportNotices(): void {
  const jobs = useJobsStore()
  const stop = jobs.onFinished((job) => {
    if (jobs.viewing !== job.analysis_id) announce(job)
  })
  onScopeDispose(stop)
}
