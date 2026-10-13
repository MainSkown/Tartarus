import type { AnalysisRead } from '@/api'
import type { ConfirmOptions } from '@/services/confirm'
import { formatFileSize } from '@/services/file-size'

export function deleteConfirmation({ id, filename, disk_bytes }: Pick<AnalysisRead, 'id' | 'filename' | 'disk_bytes'>): ConfirmOptions {
  const freed = disk_bytes > 0 ? `, freeing ${formatFileSize(disk_bytes)}` : ''
  return {
    title: `Delete #${id}`,
    message: `Delete ${filename}? Its CAPE task, sample, events and report are removed${freed}. This cannot be undone.`,
  }
}
