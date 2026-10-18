import type { AnalysisStatus } from '@/api'
import { t, type MessageKey } from '@/i18n'

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
  return t(phase === 'ending' ? 'live.endRun.labelEnding' : 'live.endRun.label')
}

const TITLES: Partial<Record<EndRunPhase, MessageKey>> = {
  waiting: 'live.endRun.title.waiting',
  ready: 'live.endRun.title.ready',
  confirming: 'live.endRun.title.confirming',
  ending: 'live.endRun.title.ending',
}

export function endRunTitle(phase: EndRunPhase): string {
  const key = TITLES[phase]
  return key === undefined ? '' : t(key)
}
