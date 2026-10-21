import type { RunningAnalysis } from '@/api'

const SECONDS_PER_MINUTE = 60
const SECONDS_PER_HOUR = 3600
const MS_PER_SECOND = 1000

/** A running clock as the header shows it: `01:12`, or `1:02:05` past an hour. */
export function clockDuration(totalSeconds: number): string {
  const seconds = Math.floor(totalSeconds)
  const hours = Math.floor(seconds / SECONDS_PER_HOUR)
  const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE)
  const clock = [minutes, seconds % SECONDS_PER_MINUTE].map((part) => String(part).padStart(2, '0')).join(':')
  return hours > 0 ? `${hours}:${clock}` : clock
}

/** Seconds a running analysis has taken as of `nowMs`, counted on from its start between queue pushes. */
export function elapsedSecondsAt(analysis: RunningAnalysis, nowMs: number): number {
  if (analysis.started_at === null) return analysis.elapsed_s ?? 0
  return Math.max(0, Math.floor((nowMs - Date.parse(analysis.started_at)) / MS_PER_SECOND))
}
