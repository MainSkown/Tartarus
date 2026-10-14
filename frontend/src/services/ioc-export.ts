import { exportIocs } from '@/api'
import type { ExportFormat } from '@/api'
import { saveDownload } from '@/services/download'

export const IOC_FORMATS: { value: ExportFormat; label: string; extension: string }[] = [
  { value: 'stix', label: 'STIX 2.1', extension: 'stix.json' },
  { value: 'misp', label: 'MISP', extension: 'misp.json' },
  { value: 'csv', label: 'CSV', extension: 'csv' },
]

export function iocFormat(format: ExportFormat): (typeof IOC_FORMATS)[number] {
  return IOC_FORMATS.find((candidate) => candidate.value === format)!
}

/** Saves the IOCs of an analysis in one format; false when the request failed (the error toast has said why). */
export function downloadIocs(analysisId: number, format: ExportFormat): Promise<boolean> {
    const request = exportIocs({ path: { analysis_id: analysisId }, query: { format }, parseAs: 'blob' })
  return saveDownload(request, `tartarus-${analysisId}-iocs.${iocFormat(format).extension}`)
}
