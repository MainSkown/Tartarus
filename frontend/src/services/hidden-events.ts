import { t, type MessageKey } from '@/i18n'

const REASON_KEYS: Record<string, MessageKey> = {
  'windows-background': 'analysis.summary.hiddenEvents.reason.windowsBackground',
  'cape-tooling': 'analysis.summary.hiddenEvents.reason.capeTooling',
  'monitor-artefact': 'analysis.summary.hiddenEvents.reason.monitorArtefact',
  'sysmon-service': 'analysis.summary.hiddenEvents.reason.sysmonService',
  'unmapped-event': 'analysis.summary.hiddenEvents.reason.unmappedEvent',
}

export interface HiddenEventReason {
  label: string
  count: number
}

// The total counts every reason, so the figures in the tooltip add up to the line they explain.
export function hiddenEventsTotal(counts: Record<string, number> | undefined): number {
  return Object.values(counts ?? {}).reduce((sum, count) => sum + count, 0)
}

export function hiddenEventBreakdown(counts: Record<string, number> | undefined): HiddenEventReason[] {
  return Object.entries(counts ?? {})
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => ({ label: reason in REASON_KEYS ? t(REASON_KEYS[reason]!) : reason, count }))
    .sort((a, b) => b.count - a.count)
}
