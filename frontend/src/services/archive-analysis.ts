import type { AnalysisRead } from '@/api'

export interface ArchiveRun {
  /** Path of the file run, inside the zip. */
  entry: string
  /** Null until the run is done, and for good when the entry started no process of its own. */
  entrySha256: string | null
}

/** Undefined for an analysis whose sample was not a submitted zip. */
export function archiveOf(analysis: AnalysisRead): ArchiveRun | undefined {
  const entry = analysis.options.archive_entry
  if (typeof entry !== 'string' || entry === '') return undefined
  return { entry, entrySha256: analysis.summary?.sample?.entry_sha256 ?? null }
}
