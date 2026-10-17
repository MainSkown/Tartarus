import type { GuestState } from '@/api'
import type { AnalysisStatusMeta } from '@/services/analysis-status'

type GuestStateMeta = Pick<AnalysisStatusMeta, 'label' | 'color' | 'icon' | 'active'>

// A Record, so a state the backend adds is a compile error here.
const STATE_META: Record<GuestState, GuestStateMeta> = {
  building: { label: 'BUILDING', color: '--blue-primary', icon: 'construction', active: true },
  testing: { label: 'TESTING', color: '--blue-primary', icon: 'science', active: true },
  ready: { label: 'READY', color: '--status-success', icon: 'check_circle', active: false },
  failed: { label: 'FAILED', color: '--status-critical', icon: 'dangerous', active: false },
  broken: { label: 'BROKEN', color: '--status-critical', icon: 'report_problem', active: false },
}

export const GUEST_STATES = Object.keys(STATE_META) as GuestState[]

export function guestStateMeta(state: GuestState): GuestStateMeta {
  // The control service may be newer than this build of the GUI.
  return STATE_META[state] ?? { label: state.toUpperCase(), color: '--text-gray', icon: 'help_outline', active: false }
}

/** A building or testing guest has a build job running; it is neither ready nor finished failing. */
export function isInProgress(state: GuestState): boolean {
  return guestStateMeta(state).active
}
