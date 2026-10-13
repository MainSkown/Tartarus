export interface AnalysisTab {
  key: string
  label: string
  available: boolean
  /** The milestone that builds a tab that is not available yet. */
  arrivesWith?: string
}

export const DEFAULT_TAB = 'summary'

export const ANALYSIS_TABS: AnalysisTab[] = [
  { key: DEFAULT_TAB, label: 'SUMMARY', available: true },
  { key: 'processes', label: 'PROCESSES', available: true },
  { key: 'timeline', label: 'TIMELINE', available: false, arrivesWith: 'M3' },
  { key: 'events', label: 'EVENTS', available: false, arrivesWith: 'M3' },
  { key: 'network', label: 'NETWORK', available: true },
  { key: 'artifacts', label: 'ARTIFACTS', available: true },
  { key: 'detections', label: 'DETECTIONS', available: true },
  { key: 'notes', label: 'NOTES', available: false, arrivesWith: 'M4' },
]

/** The tab to mark selected: the requested one only if it is built, otherwise the default. */
export function selectableTab(key: string): string {
  return ANALYSIS_TABS.some((tab) => tab.key === key && tab.available) ? key : DEFAULT_TAB
}

export function arrivalNote(key: string): string {
  const milestone = ANALYSIS_TABS.find((tab) => tab.key === key)?.arrivesWith
  return `${key} arrives${milestone ? ` with ${milestone}` : ' later'}`
}
