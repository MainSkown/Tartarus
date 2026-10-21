import type { ConfirmOptions } from '@/services/confirm'
import { isInProgress } from '@/services/guest-state'
import { t, type MessageKey } from '@/i18n'
import type { Guest, GuestProfile, GuestResources, HealthProbe } from '@/api'

export interface SelfTestSummary {
  message: string
  /** The analysis of the benign sample, when the test got as far as submitting it. */
  analysisId: number | undefined
}

export const GIVEAWAY_ADVICE: MessageKey = 'guests.card.giveawayAdvice'

export function kindLabel(guest: Guest): string | undefined {
  if (guest.adopted) return t('guests.kind.adopted')
  if (guest.cloned_from) return t('guests.kind.clone', { source: guest.cloned_from })
  return guest.kind?.toUpperCase()
}

const BARE_INDEX = /^\d+$/

/**
 * "Windows 11 Pro". The edition name the media gave already says which OS it is, so it is the whole label;
 * without it the profile's name stands alone. A guest record keeps only the edition's index, which means
 * nothing to read, so a bare number is never shown.
 */
export function systemLabel(
  guest: Guest,
  profile: GuestProfile | undefined,
  edition?: string,
): string | undefined {
  if (edition) return edition
  const variant = guest.media?.variant
  const named = variant && !BARE_INDEX.test(variant) ? variant : undefined
  const parts = [profile?.display_name ?? guest.profile, named].filter(Boolean)
  return parts.length > 0 ? parts.join(' ') : undefined
}

export function resourcesLabel({ vcpus, ram_mb, disk_gb }: GuestResources): string {
  const ram = ram_mb % 1024 === 0 ? t('guests.resources.gigabytes', { count: ram_mb / 1024 }) : t('guests.resources.megabytes', { count: ram_mb })
  return t('guests.resources.summary', { cpus: t('guests.resources.vcpus', vcpus), ram, disk: disk_gb })
}

export function selfTestOf(guest: Guest): SelfTestSummary | undefined {
  const { message, analysis_id } = guest.selftest ?? {}
  if (typeof message !== 'string') return undefined
  return { message, analysisId: typeof analysis_id === 'number' ? analysis_id : undefined }
}

export function checkSummary(probes: readonly HealthProbe[]): string {
  const passed = probes.filter((probe) => probe.ok).length
  return t('guests.checks.summary', { passed, total: probes.length }, probes.length)
}

export function guestDeleteConfirmation(name: string): ConfirmOptions {
  return {
    title: t('guests.delete.title', { name }),
    message: t('guests.delete.message', { name }),
  }
}

export interface GuestActions {
  runChecks: boolean
  clone: boolean
  remove: boolean
  viewBuild: boolean
  retestSelfTest: boolean
}

/**
 * What the analyst may do with a guest in its state: only a ready one is checked or cloned, and nothing but its build is open while it builds.
 * A failed guest carries a self-test verdict only when its build finished, which is what makes running the self-test again possible; the
 * control service still refuses a guest whose build did not.
 */
export function guestActions(guest: Guest): GuestActions {
  const ready = guest.state === 'ready'
  const settled = !isInProgress(guest.state)
  return {
    runChecks: ready,
    clone: ready,
    remove: settled,
    viewBuild: guest.build_id != null && guest.state !== 'ready' && guest.state !== 'broken',
    retestSelfTest: guest.state === 'failed' && guest.selftest != null,
  }
}
