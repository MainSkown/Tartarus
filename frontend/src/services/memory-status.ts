import type { MemorySummary } from '@/api'
import { t } from '@/i18n'
import { formatFileSize } from '@/services/file-size'
import { formatCount } from '@/services/format-number'

export function dumpStatusText(memory: MemorySummary): string {
  if (!memory.dump_taken) return t('analysis.summary.memory.dumpNotTaken')
  return memory.dump_bytes == null
    ? t('analysis.summary.memory.dumpTakenNoSize')
    : t('analysis.summary.memory.dumpTaken', { size: formatFileSize(memory.dump_bytes) })
}

export function findingsStatusText(memory: MemorySummary, findingCount?: number | null): string {
  if (memory.findings === 'unavailable') return t('analysis.summary.memory.findingsUnavailable')
  if (memory.findings === 'failed') return t('analysis.summary.memory.findingsFailed')
  if (findingCount == null) return t('analysis.summary.memory.findingsOk')
  return t('analysis.summary.memory.findingsOkCount', { count: formatCount(findingCount) }, findingCount)
}

export function dumpFileStatus(memory: MemorySummary): { text: string; warn: boolean } | null {
  if (!memory.dump_taken) return null
  if (memory.dump_deleted === true) return { text: t('analysis.summary.memory.deleted'), warn: false }
  if (memory.dump_deleted === false) return { text: t('analysis.summary.memory.deleteFailed'), warn: true }
  return { text: t('analysis.summary.memory.kept'), warn: false }
}
