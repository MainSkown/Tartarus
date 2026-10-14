import { Dialog } from 'quasar'
import type { AnalysisRead, ReportVariant } from '@/api'
import ReportDialog from '@/components/ReportDialog.vue'

export function openReportDialog(analysis: Pick<AnalysisRead, 'id' | 'filename'>, format: ReportVariant): void {
  Dialog.create({
    component: ReportDialog,
    componentProps: { analysisId: analysis.id, filename: analysis.filename, initialFormat: format },
  })
}
