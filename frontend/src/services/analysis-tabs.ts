import type { AnalysisRead, AnalysisStatus } from '@/api'
import { isTerminalStatus } from '@/services/analysis-status'

export interface AnalysisTab {
  key: string
  label: string
  available: boolean
  /** The milestone that builds a tab that is not available yet. */
  arrivesWith?: string
  /** Listed only during a live session (see `nextLiveSession`), never for an analysis opened already finished. */
  liveOnly?: boolean
  /** Filtered by the shared query bar and chips, which the page shows under the tab strip. */
  queryable?: boolean
  /** Works on an analysis that is not done yet; every other view needs the ingested run. */
  usableBeforeDone?: boolean
}

export const DEFAULT_TAB = 'summary'
export const LIVE_TAB = 'live'

export const ANALYSIS_TABS: AnalysisTab[] = [
  { key: LIVE_TAB, label: 'LIVE', available: true, liveOnly: true },
  { key: DEFAULT_TAB, label: 'SUMMARY', available: true },
  { key: 'processes', label: 'PROCESSES', available: true },
  { key: 'timeline', label: 'TIMELINE', available: true, queryable: true },
  { key: 'events', label: 'EVENTS', available: true, queryable: true },
  { key: 'network', label: 'NETWORK', available: true },
  { key: 'artifacts', label: 'ARTIFACTS', available: true },
  { key: 'detections', label: 'DETECTIONS', available: true },
  { key: 'notes', label: 'NOTES', available: true, usableBeforeDone: true },
]

export function isQueryableTab(key: string): boolean {
  return ANALYSIS_TABS.some((tab) => tab.key === key && tab.queryable === true)
}

export function isUsableBeforeDone(key: string): boolean {
  return ANALYSIS_TABS.some((tab) => tab.key === key && tab.usableBeforeDone === true)
}

/** Whether a run is still going on, from queued to ingesting: the states the LIVE tab exists for. */
export function isLiveStatus(status: AnalysisStatus): boolean {
  return !isTerminalStatus(status)
}

export function listedTabs(liveSession: boolean): AnalysisTab[] {
  return ANALYSIS_TABS.filter((tab) => liveSession || !tab.liveOnly)
}

/** The tab to mark selected: the requested one only if it is built and listed, otherwise the default. */
export function selectableTab(key: string, liveSession = false): string {
  return listedTabs(liveSession).some((tab) => tab.key === key && tab.available) ? key : DEFAULT_TAB
}

/**
 * Whether the LIVE tab is listed. It starts as soon as the analysis is seen active, on whatever
 * tab the page was opened, and stays for the rest of the page session: the user can leave it for
 * another tab and come back, also after the run has finished. An analysis opened already finished
 * never gets it.
 */
export function nextLiveSession(wasLive: boolean, analysis: AnalysisRead | undefined): boolean {
  return wasLive || (analysis !== undefined && isLiveStatus(analysis.status))
}

export function arrivalNote(key: string): string {
  const milestone = ANALYSIS_TABS.find((tab) => tab.key === key)?.arrivesWith
  return `${key} arrives${milestone ? ` with ${milestone}` : ' later'}`
}
