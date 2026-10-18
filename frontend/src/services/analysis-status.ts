import type { AnalysisStatus, Severity } from '@/api'
import { t, type MessageKey } from '@/i18n'

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

type WithLabelKey<Meta> = Omit<Meta, 'label'> & { labelKey: MessageKey }

// Typed as Records so a status or severity the backend adds is a compile error here. The label is a key, translated when read.
const STATUS_META: Record<AnalysisStatus, WithLabelKey<AnalysisStatusMeta>> = {
  queued: { labelKey: 'analysis.status.queued', color: '--text-gray', icon: 'schedule', active: false, terminal: false },
  starting: { labelKey: 'analysis.status.starting', color: '--blue-primary', icon: 'hourglass_top', active: true, terminal: false },
  running: { labelKey: 'analysis.status.running', color: '--blue-primary', icon: 'play_arrow', active: true, terminal: false },
  processing: { labelKey: 'analysis.status.processing', color: '--blue-primary', icon: 'settings', active: true, terminal: false },
  ingesting: { labelKey: 'analysis.status.ingesting', color: '--blue-primary', icon: 'move_to_inbox', active: true, terminal: false },
  done: { labelKey: 'analysis.status.done', color: '--status-success', icon: 'check_circle', active: false, terminal: true },
  failed: { labelKey: 'analysis.status.failed', color: '--status-critical', icon: 'dangerous', active: false, terminal: true },
  report_failed: {
    labelKey: 'analysis.status.reportFailed',
    color: '--status-critical',
    icon: 'report_problem',
    active: false,
    terminal: true,
  },
  cancelled: { labelKey: 'analysis.status.cancelled', color: '--text-gray-dark', icon: 'cancel', active: false, terminal: true },
}

const SEVERITY_META: Record<Severity, WithLabelKey<SeverityMeta>> = {
  info: { labelKey: 'analysis.severity.info', color: '--status-info', icon: 'info_outline', rank: 0 },
  low: { labelKey: 'analysis.severity.low', color: '--status-low', icon: 'info', rank: 1 },
  medium: { labelKey: 'analysis.severity.medium', color: '--status-medium', icon: 'report', rank: 2 },
  high: { labelKey: 'analysis.severity.high', color: '--status-high', icon: 'warning', rank: 3 },
  critical: { labelKey: 'analysis.severity.critical', color: '--status-critical', icon: 'dangerous', rank: 4 },
}

export const ANALYSIS_STATUSES = Object.keys(STATUS_META) as AnalysisStatus[]

/** Lowest severity first. */
export const SEVERITIES = (Object.keys(SEVERITY_META) as Severity[]).sort(compareSeverity)

export function analysisStatusMeta(status: AnalysisStatus): AnalysisStatusMeta {
  const { labelKey, ...rest } = STATUS_META[status]
  return { label: t(labelKey), ...rest }
}

export function isActiveStatus(status: AnalysisStatus): boolean {
  return STATUS_META[status].active
}

export function isTerminalStatus(status: AnalysisStatus): boolean {
  return STATUS_META[status].terminal
}

/** The backend re-ingests only an analysis whose indexing ended, whether it finished or its report failed. */
export function canReingest(status: AnalysisStatus): boolean {
  return status === 'done' || status === 'report_failed'
}

export function severityMeta(severity: Severity): SeverityMeta {
  const { labelKey, ...rest } = SEVERITY_META[severity]
  return { label: t(labelKey), ...rest }
}

export function compareSeverity(a: Severity, b: Severity): number {
  return SEVERITY_META[a].rank - SEVERITY_META[b].rank
}

/** The severity at a position of the scale (the number `event.severity` carries); a number off the scale is info. */
export function severityOfRank(rank: number): Severity {
  return SEVERITIES[rank] ?? 'info'
}
