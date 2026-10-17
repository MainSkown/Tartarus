import type { ConfirmOptions } from '@/services/confirm'
import { isInProgress } from '@/services/guest-state'
import type { Guest, GuestProfile, GuestResources, HealthProbe } from '@/api'

export interface SelfTestSummary {
  message: string
  /** The analysis of the benign sample, when the test got as far as submitting it. */
  analysisId: number | undefined
}

export const GIVEAWAY_ADVICE = 'Rebuild or clone for a clean guest.'

export function kindLabel(guest: Guest): string | undefined {
  if (guest.adopted) return 'ADOPTED'
  if (guest.cloned_from) return `CLONE OF ${guest.cloned_from}`
  return guest.kind?.toUpperCase()
}

/** "Windows 11 Pro": what the profile calls the OS, then the edition the media carried. */
export function systemLabel(guest: Guest, profile: GuestProfile | undefined): string | undefined {
  const parts = [profile?.display_name ?? guest.profile, guest.media?.variant].filter(Boolean)
  return parts.length > 0 ? parts.join(' ') : undefined
}

export function resourcesLabel({ vcpus, ram_mb, disk_gb }: GuestResources): string {
  const ram = ram_mb % 1024 === 0 ? `${ram_mb / 1024} GB` : `${ram_mb} MB`
  return `${vcpus} ${vcpus === 1 ? 'vCPU' : 'vCPUs'} · ${ram} RAM · ${disk_gb} GB disk`
}

export function selfTestOf(guest: Guest): SelfTestSummary | undefined {
  const { message, analysis_id } = guest.selftest ?? {}
  if (typeof message !== 'string') return undefined
  return { message, analysisId: typeof analysis_id === 'number' ? analysis_id : undefined }
}

export function checkSummary(probes: readonly HealthProbe[]): string {
  const passed = probes.filter((probe) => probe.ok).length
  return `${passed} of ${probes.length} ${probes.length === 1 ? 'check' : 'checks'} passed`
}

export function guestDeleteConfirmation(name: string): ConfirmOptions {
  return {
    title: `Delete ${name}`,
    message: `Delete the guest ${name}? Its virtual machine, disk and snapshot are removed and it is unregistered from CAPE; analyses that used it keep their data. This cannot be undone.`,
  }
}

export interface GuestActions {
  runChecks: boolean
  clone: boolean
  remove: boolean
  viewBuild: boolean
}

/** What the analyst may do with a guest in its state: only a ready one is checked or cloned, and nothing but its build is open while it builds. */
export function guestActions(guest: Guest): GuestActions {
  const ready = guest.state === 'ready'
  const settled = !isInProgress(guest.state)
  return {
    runChecks: ready,
    clone: ready,
    remove: settled,
    viewBuild: guest.build_id != null && guest.state !== 'ready' && guest.state !== 'broken',
  }
}
