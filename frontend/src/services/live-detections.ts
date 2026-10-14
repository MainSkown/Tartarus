import type { Severity } from '@/api'
import { severityOfRank } from '@/services/analysis-status'
import type { LiveEvent } from '@/services/live-messages'

export const MAX_LIVE_DETECTIONS = 500

export interface LiveDetection {
  id: string
  name: string
  ruleset: string
  severity: Severity
  techniques: string[]
  time: string
  process: { pid: number; name: string | null } | null
}

/** A detection reaches the LIVE tab as an `event.kind: alert` document in the same `events` batch as its trigger. */
export function liveDetectionOf(event: LiveEvent): LiveDetection | undefined {
  if (event.event.kind !== 'alert') return undefined
  const pid = event.process?.pid
  return {
    id: event.event.id,
    name: event.rule?.name ?? event.tartarus.summary,
    ruleset: event.rule?.ruleset ?? 'unknown',
    severity: severityOfRank(event.event.severity ?? 0),
    techniques: event.threat?.technique?.id ?? [],
    time: event['@timestamp'],
    process: pid === undefined ? null : { pid, name: event.process?.name ?? null },
  }
}

/** The known detections plus the new alerts of a batch, each alert once, the newest `MAX_LIVE_DETECTIONS` kept. */
export function collectDetections(known: readonly LiveDetection[], batch: readonly LiveEvent[]): readonly LiveDetection[] {
  const seen = new Set(known.map((detection) => detection.id))
  const fresh = batch
    .map(liveDetectionOf)
    .filter((detection): detection is LiveDetection => detection !== undefined && !seen.has(detection.id))
  if (fresh.length === 0) return known
  return [...known, ...fresh].slice(-MAX_LIVE_DETECTIONS)
}
