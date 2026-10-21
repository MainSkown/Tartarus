import { t } from '@/i18n'
import { humanStepName } from '@/services/guest-build'

// The control service logs each step's output as it printed it: `LOG text`, `STEP title`, `PROGRESS n`,
// and its own `== step name` line where a step starts.
const LOG_PREFIX = 'LOG '
const GUEST_PREFIX = 'guest: '
const STEP_STARTS = /^== step (\S+)$/
const PROGRESS_LINE = /^PROGRESS (\d{1,3})$/

export type LogRow =
  | { kind: 'text'; index: number; text: string; fromGuest: boolean }
  | { kind: 'progress'; index: number; percent: number; label: string }

/** The log as the panel draws it: protocol words dropped, and each PROGRESS figure named after the step it belongs to. */
export function logRows(lines: readonly string[]): LogRow[] {
  let step: string | undefined
  return lines.map((line, index): LogRow => {
    const started = STEP_STARTS.exec(line)
    if (started) step = started[1]
    const progress = PROGRESS_LINE.exec(line)
    if (progress) {
      const percent = Number(progress[1])
      const label = step ? t('guests.buildLog.progress', { step: humanStepName(step), percent }) : t('guests.buildLog.progressUnnamed', { percent })
      return { kind: 'progress', index, percent, label }
    }
    const text = line.startsWith(LOG_PREFIX) ? line.slice(LOG_PREFIX.length) : line
    return { kind: 'text', index, text, fromGuest: text.startsWith(GUEST_PREFIX) }
  })
}
