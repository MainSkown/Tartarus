import { t } from '@/i18n'

export const EXTEND_STEP_S = 60
// CAPE's own limit for an interactive task; the backend never moves a deadline past start + this.
export const LONGEST_RUN_S = 20 * 60

const LONGEST_RUN_MINUTES = LONGEST_RUN_S / 60

export function extendLabel(): string {
  return t('live.extend.label', { seconds: EXTEND_STEP_S })
}

export function extendTitle(atLongest: boolean): string {
  return atLongest
    ? t('live.extend.longest', { minutes: LONGEST_RUN_MINUTES }, LONGEST_RUN_MINUTES)
    : t('live.extend.adds', { seconds: EXTEND_STEP_S }, EXTEND_STEP_S)
}
