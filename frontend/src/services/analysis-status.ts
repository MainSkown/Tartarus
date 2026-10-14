import type { AnalysisStatus, Severity } from '@/api'

export interface AnalysisStatusMeta {
  label: string
  /** Name of a CSS custom property from app.css, without the `var()` wrapper. */
  color: string
  /** Material Icons name. */
  icon: string
  /** The backend's active set: the analysis is on its way through CAPE right now. */
  active: boolean
  terminal: boolean
}

export interface SeverityMeta {
  label: string
  color: string
  icon: string
  /** Position on the scale, 0 for info up to 4 for critical. */
  rank: number
}

// Typed as Records so a status or severity the backend adds is a compile error here.
const STATUS_META: Record<AnalysisStatus, AnalysisStatusMeta> = {
  queued: { label: 'QUEUED', color: '--text-gray', icon: 'schedule', active: false, terminal: false },
  starting: { label: 'STARTING', color: '--blue-primary', icon: 'hourglass_top', active: true, terminal: false },
  running: { label: 'RUNNING', color: '--blue-primary', icon: 'play_arrow', active: true, terminal: false },
  processing: { label: 'PROCESSING', color: '--blue-primary', icon: 'settings', active: true, terminal: false },
  ingesting: { label: 'INGESTING', color: '--blue-primary', icon: 'move_to_inbox', active: true, terminal: false },
  done: { label: 'DONE', color: '--status-success', icon: 'check_circle', active: false, terminal: true },
  failed: { label: 'FAILED', color: '--status-critical', icon: 'dangerous', active: false, terminal: true },
  report_failed: {
    label: 'REPORT FAILED',
    color: '--status-critical',
    icon: 'report_problem',
    active: false,
    terminal: true,
  },
  cancelled: { label: 'CANCELLED', color: '--text-gray-dark', icon: 'cancel', active: false, terminal: true },
}

const SEVERITY_META: Record<Severity, SeverityMeta> = {
  info: { label: 'INFO', color: '--status-info', icon: 'info_outline', rank: 0 },
  low: { label: 'LOW', color: '--status-low', icon: 'info', rank: 1 },
  medium: { label: 'MEDIUM', color: '--status-medium', icon: 'report', rank: 2 },
  high: { label: 'HIGH', color: '--status-high', icon: 'warning', rank: 3 },
  critical: { label: 'CRITICAL', color: '--status-critical', icon: 'dangerous', rank: 4 },
}

export const ANALYSIS_STATUSES = Object.keys(STATUS_META) as AnalysisStatus[]

/** Lowest severity first. */
export const SEVERITIES = (Object.keys(SEVERITY_META) as Severity[]).sort(compareSeverity)

export function analysisStatusMeta(status: AnalysisStatus): AnalysisStatusMeta {
  return STATUS_META[status]
}

export function isActiveStatus(status: AnalysisStatus): boolean {
  return STATUS_META[status].active
}

export function isTerminalStatus(status: AnalysisStatus): boolean {
  return STATUS_META[status].terminal
}

export function severityMeta(severity: Severity): SeverityMeta {
  return SEVERITY_META[severity]
}

export function compareSeverity(a: Severity, b: Severity): number {
  return SEVERITY_META[a].rank - SEVERITY_META[b].rank
}

/** The severity at a position of the scale (the number `event.severity` carries); a number off the scale is info. */
export function severityOfRank(rank: number): Severity {
  return SEVERITIES[rank] ?? 'info'
}
