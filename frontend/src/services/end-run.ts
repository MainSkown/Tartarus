import type { AnalysisStatus } from '@/api'

export type EndRunPhase = 'hidden' | 'waiting' | 'ready' | 'confirming' | 'ending'

export interface EndRunInput {
  status: AnalysisStatus
  /** The live feed has shown the first process or event, so the monitor is running in the guest. */
  monitorUp: boolean
  confirming: boolean
  /** The server accepted the request, or it is on its way. */
  ending: boolean
  /** The server just said the guest has not started: asking again at once would only repeat it. */
  cooling: boolean
}

export function endRunPhase({ status, monitorUp, confirming, ending, cooling }: EndRunInput): EndRunPhase {
  if (status !== 'running') return 'hidden'
  if (ending) return 'ending'
  if (confirming) return 'confirming'
  return monitorUp && !cooling ? 'ready' : 'waiting'
}

export function endRunLabel(phase: EndRunPhase): string {
  return phase === 'ending' ? 'ENDING...' : 'END RUN'
}

const TITLES: Record<EndRunPhase, string> = {
  hidden: '',
  waiting: 'The analysis has not started in the guest yet. The run can be ended in a few seconds.',
  ready: 'Stops the guest now; CAPE processes what was collected so far.',
  confirming: 'Waiting for your answer.',
  ending: 'The guest is stopping. The analysis moves on to processing in a few seconds.',
}

export function endRunTitle(phase: EndRunPhase): string {
  return TITLES[phase]
}
