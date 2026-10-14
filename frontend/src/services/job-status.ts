import type { JobStatus } from '@/api'

// A Record, so a status the backend adds is a compile error here.
const STATUS_FINISHED: Record<JobStatus, boolean> = {
  pending: false,
  running: false,
  done: true,
  failed: true,
  interrupted: true,
}

export const JOB_STATUSES = Object.keys(STATUS_FINISHED) as JobStatus[]

export function isFinishedJob(status: JobStatus): boolean {
  return STATUS_FINISHED[status]
}
