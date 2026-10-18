import { t } from '@/i18n'
import { formatDuration } from '@/services/format-duration'

export const WARNING_WINDOW_S = 30
const NOTHING = '–'

export interface CountdownRun {
  interactive: boolean
  running: boolean
}

export interface CountdownDisplay {
  text: string
  warning: boolean
}

export function shownDuration(seconds: number | null): string {
  return seconds === null ? NOTHING : formatDuration(seconds)
}

export function countdownDisplay(seconds: number | null, run: CountdownRun): CountdownDisplay {
  if (seconds === null) return { text: NOTHING, warning: false }
  if (!run.interactive || !run.running) return { text: formatDuration(seconds), warning: false }
  if (Math.round(seconds) === 0) return { text: t('live.countdown.ending'), warning: true }
  return { text: formatDuration(seconds), warning: seconds <= WARNING_WINDOW_S }
}
