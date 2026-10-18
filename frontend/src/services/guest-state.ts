import type { GuestState } from '@/api'
import { t, type MessageKey } from '@/i18n'
import type { AnalysisStatusMeta } from '@/services/analysis-status'

type GuestStateMeta = Pick<AnalysisStatusMeta, 'label' | 'color' | 'icon' | 'active'>
type StateEntry = Omit<GuestStateMeta, 'label'> & { labelKey: MessageKey }

// A Record, so a state the backend adds is a compile error here. The label is a key, translated when read.
const STATE_META: Record<GuestState, StateEntry> = {
  building: { labelKey: 'guests.state.building', color: '--blue-primary', icon: 'construction', active: true },
  testing: { labelKey: 'guests.state.testing', color: '--blue-primary', icon: 'science', active: true },
  ready: { labelKey: 'guests.state.ready', color: '--status-success', icon: 'check_circle', active: false },
  failed: { labelKey: 'guests.state.failed', color: '--status-critical', icon: 'dangerous', active: false },
  broken: { labelKey: 'guests.state.broken', color: '--status-critical', icon: 'report_problem', active: false },
}

export const GUEST_STATES = Object.keys(STATE_META) as GuestState[]

export function guestStateMeta(state: GuestState): GuestStateMeta {
  // The control service may be newer than this build of the GUI.
  const known = STATE_META[state]
  if (!known) return { label: state.toUpperCase(), color: '--text-gray', icon: 'help_outline', active: false }
  const { labelKey, ...rest } = known
  return { label: t(labelKey), ...rest }
}

/** A building or testing guest has a build job running; it is neither ready nor finished failing. */
export function isInProgress(state: GuestState): boolean {
  return guestStateMeta(state).active
}
