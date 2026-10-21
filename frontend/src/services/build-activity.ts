import { t } from '@/i18n'
import { formatDuration } from '@/services/format-duration'

/** Past this much silence from the running step the page stops calling it quiet and warns. */
export const STALE_AFTER_S = 120
export const ACTIVITY_TICK_MS = 1_000

const MS_PER_SECOND = 1000
const SECONDS_PER_MINUTE = 60

export interface ActivityNotice {
  text: string
  stale: boolean
}

/** Seconds since `lastActivity`, never negative; undefined while the build has shown none or the time does not parse. */
export function activityAgeSeconds(lastActivity: string | null | undefined, now: number): number | undefined {
  if (!lastActivity) return undefined
  const then = Date.parse(lastActivity)
  if (Number.isNaN(then)) return undefined
  return Math.max(0, Math.round((now - then) / MS_PER_SECOND))
}

export function activityNotice(ageSeconds: number): ActivityNotice {
  if (ageSeconds >= STALE_AFTER_S) {
    return { text: t('guests.build.activity.stale', { minutes: Math.floor(ageSeconds / SECONDS_PER_MINUTE) }), stale: true }
  }
  return { text: t('guests.build.activity.ago', { age: formatDuration(ageSeconds) }), stale: false }
}
