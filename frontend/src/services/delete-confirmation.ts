import type { AnalysisRead } from '@/api'
import { t } from '@/i18n'
import type { ConfirmOptions } from '@/services/confirm'
import { formatFileSize } from '@/services/file-size'

export function deleteConfirmation({ id, filename, disk_bytes }: Pick<AnalysisRead, 'id' | 'filename' | 'disk_bytes'>): ConfirmOptions {
  return {
    title: t('guests.analysisDelete.title', { id }),
    message: disk_bytes > 0
      ? t('guests.analysisDelete.messageFreeing', { filename, size: formatFileSize(disk_bytes) })
      : t('guests.analysisDelete.message', { filename }),
  }
}
