import type { DefenderStatus, DefenderVerdict, Outcome } from '@/api'
import type { MessageKey } from '@/i18n'

// A Defender-off guest exports no log and the backend reports `clean` for it, so the badge, not the
// verdict, says whether the verdict means anything.
const DEFENDER_ON_BADGE = 'DEFENDER ON'

export function guestRunsDefender(badges: readonly string[]): boolean {
  return badges.includes(DEFENDER_ON_BADGE)
}

export interface VerdictHeadline {
  messageKey: MessageKey
  detailKey?: MessageKey
  /** CSS custom property of the icon and the left border. */
  color: string
  icon: string
}

const HEADLINES: Record<Exclude<DefenderStatus, 'removed'>, VerdictHeadline> = {
  detected: {
    messageKey: 'analysis.summary.defender.detected',
    detailKey: 'analysis.summary.defender.detectedDetail',
    color: '--status-high',
    icon: 'warning',
  },
  failed: { messageKey: 'analysis.summary.defender.failed', color: '--status-critical', icon: 'dangerous' },
  clean: { messageKey: 'analysis.summary.defender.clean', color: '--text-gray', icon: 'shield' },
  no_export: {
    messageKey: 'analysis.summary.defender.noExport',
    detailKey: 'analysis.summary.defender.noExportDetail',
    color: '--text-gray-dark',
    icon: 'help_outline',
  },
}

const REMOVED = { color: '--blue-primary', icon: 'gpp_good' }

export function verdictHeadline(verdict: DefenderVerdict): VerdictHeadline {
  if (verdict.status !== 'removed') return HEADLINES[verdict.status]
  if (verdict.blocked_before_run) {
    return { ...REMOVED, messageKey: 'analysis.summary.defender.blockedBeforeRun', detailKey: 'analysis.summary.defender.blockedBeforeRunDetail' }
  }
  const messageKey = verdict.sample_removed
    ? 'analysis.summary.defender.removedSample'
    : 'analysis.summary.defender.removedDropped'
  return { ...REMOVED, messageKey }
}

export const OUTCOME_META: Record<Outcome, { labelKey: MessageKey; color: string }> = {
  removed: { labelKey: 'analysis.summary.defender.outcome.removed', color: '--blue-primary' },
  failed: { labelKey: 'analysis.summary.defender.outcome.failed', color: '--status-critical' },
  pending: { labelKey: 'analysis.summary.defender.outcome.pending', color: '--status-high' },
}
