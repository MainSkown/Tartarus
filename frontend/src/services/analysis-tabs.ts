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
}

export const DEFAULT_TAB = 'summary'
export const LIVE_TAB = 'live'

export const ANALYSIS_TABS: AnalysisTab[] = [
  { key: LIVE_TAB, label: 'LIVE', available: true, liveOnly: true },
  { key: DEFAULT_TAB, label: 'SUMMARY', available: true },
  { key: 'processes', label: 'PROCESSES', available: true },
  { key: 'timeline', label: 'TIMELINE', available: false, arrivesWith: 'M3' },
  { key: 'events', label: 'EVENTS', available: false, arrivesWith: 'M3' },
  { key: 'network', label: 'NETWORK', available: true },
  { key: 'artifacts', label: 'ARTIFACTS', available: true },
  { key: 'detections', label: 'DETECTIONS', available: true },
  { key: 'notes', label: 'NOTES', available: false, arrivesWith: 'M4' },
]

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
 * Whether the LIVE tab is listed. It starts when an active analysis is opened on no tab or on
 * LIVE, survives the analysis finishing (so the user is not thrown out of the tab they are on),
 * and ends when they pick another tab.
 */
export function nextLiveSession(
  wasLive: boolean,
  requestedTab: string | undefined,
  analysis: AnalysisRead | undefined,
): boolean {
  if (requestedTab !== undefined && requestedTab !== LIVE_TAB) return false
  if (analysis === undefined) return wasLive
  return wasLive || isLiveStatus(analysis.status)
}

export function arrivalNote(key: string): string {
  const milestone = ANALYSIS_TABS.find((tab) => tab.key === key)?.arrivesWith
  return `${key} arrives${milestone ? ` with ${milestone}` : ' later'}`
}
