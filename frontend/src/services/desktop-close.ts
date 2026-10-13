import type { AnalysisStatus } from '@/api'

export type DesktopPhase =
  | 'connecting'
  | 'waiting'
  | 'connected'
  | 'ended'
  | 'unavailable'
  | 'not-running'
  | 'timeout'
  | 'unreachable'
  | 'failed'

// The backend's close codes of WS /ws/analyses/{id}/desktop (docs/specs/backend.md).
const CLOSE_NORMAL = 1000
const CLOSE_UNREACHABLE = 1011
const CLOSE_PORT_TIMEOUT = 4408
const CLOSE_NOT_RUNNING = 4409

/** Keyed on the close code: the reason text is prose for people, never a status. */
export function phaseAfterClose(code: number, wasConnected: boolean): DesktopPhase {
  switch (code) {
    case CLOSE_NORMAL:
      return wasConnected ? 'ended' : 'unavailable'
    case CLOSE_PORT_TIMEOUT:
      return 'timeout'
    case CLOSE_NOT_RUNNING:
      return 'not-running'
    case CLOSE_UNREACHABLE:
      return 'unreachable'
    default:
      return 'failed'
  }
}

/** guacd's own `error` instruction: the guest is off, or its screen went away. */
export function phaseAfterGuacdError(wasConnected: boolean): DesktopPhase {
  return phaseAfterClose(CLOSE_NORMAL, wasConnected)
}

const RETRY_LABELS: Partial<Record<DesktopPhase, string>> = {
  timeout: '[RETRY]',
  unreachable: '[RETRY]',
  unavailable: '[RETRY]',
  ended: '[RECONNECT]',
  failed: '[RECONNECT]',
}

export function retryLabel(phase: DesktopPhase): string | undefined {
  return RETRY_LABELS[phase]
}

const MESSAGES: Record<DesktopPhase, string> = {
  connecting: 'connecting to the desktop...',
  waiting: 'waiting for the guest to start...',
  connected: 'connected',
  ended: 'the desktop has closed',
  unavailable: 'the desktop is not available: the guest is not running',
  'not-running': 'the desktop is only available while the analysis runs',
  timeout: 'the desktop is not available yet',
  unreachable: 'the desktop service is unreachable',
  failed: 'the desktop connection was lost',
}

export function phaseMessage(phase: DesktopPhase, reason?: string): string {
  return phase === 'timeout' && reason ? reason : MESSAGES[phase]
}

/** The backend admits a desktop only while the guest is being started or is running. */
export function hasDesktop(status: AnalysisStatus): boolean {
  return status === 'starting' || status === 'running'
}
