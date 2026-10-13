export interface AnalysisTab {
  key: string
  label: string
  available: boolean
}

export const DEFAULT_TAB = 'summary'

// M1b builds the remaining tabs; until then they show disabled so the workspace already has its shape.
export const ANALYSIS_TABS: AnalysisTab[] = [
  { key: DEFAULT_TAB, label: 'SUMMARY', available: true },
  ...['processes', 'timeline', 'events', 'network', 'artifacts', 'detections', 'notes'].map((key) => ({
    key,
    label: key.toUpperCase(),
    available: false,
  })),
]
