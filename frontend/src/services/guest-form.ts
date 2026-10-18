import type { GuestProfile, GuestResources, IdentityRule, ProfileOption } from '@/api'
import { t, type MessageKey } from '@/i18n'

export const BLANK_IDENTITY_LABEL: MessageKey = 'guests.form.blankIdentity'

const NAME_RULE: MessageKey = 'guests.form.nameRule'
const GUEST_NAME = /^[a-z][a-z0-9-]{1,31}$/

export type OptionValues = Record<string, unknown>
export type ResourceField = keyof GuestResources
export type ResourceProblems = Partial<Record<ResourceField, string>>

export interface ProfileDefaults {
  options: OptionValues
  resources: GuestResources
}

export function guestNameProblem(name: string, taken: readonly string[]): string | undefined {
  if (!GUEST_NAME.test(name)) return t(NAME_RULE)
  return taken.includes(name) ? t('guests.form.nameTaken', { name }) : undefined
}

function fullMatch(pattern: string): RegExp | undefined {
  try {
    return new RegExp(`^(?:${pattern})$`)
  } catch {
    // The profile's patterns are Python regexes; one that uses syntax JavaScript lacks is left to the server.
    return undefined
  }
}

/** Why a typed identity value breaks the profile's rule, or nothing for a blank (chosen at build time) or a good one. The giveaway list stays the server's: it answers with its own message. */
export function identityProblem(rule: IdentityRule, value: string): string | undefined {
  if (value === '') return undefined
  if (fullMatch(rule.pattern)?.test(value) === false) return t('guests.form.mustMatch', { label: rule.label, pattern: rule.pattern })
  const reserved = (rule.reserved ?? []).some((name) => name.toLowerCase() === value.toLowerCase())
  return reserved ? t('guests.form.reserved', { value }) : undefined
}

export function resourceProblems(resources: GuestResources, minDiskGb: number): ResourceProblems {
  const problems: ResourceProblems = {}
  for (const field of ['vcpus', 'ram_mb', 'disk_gb'] as const) {
    if (!Number.isInteger(resources[field]) || resources[field] < 1) problems[field] = t('guests.form.wholeNumber')
  }
  if (!problems.disk_gb && resources.disk_gb < minDiskGb) problems.disk_gb = t('guests.form.minDisk', { gb: minDiskGb })
  return problems
}

function emptyValueOf(option: ProfileOption): unknown {
  if (option.type === 'bool') return false
  if (option.type === 'choice') return option.choices?.[0] ?? ''
  return ''
}

export function profileDefaults(profile: GuestProfile): ProfileDefaults {
  const { vcpus, ram_mb, disk_gb } = profile.resources
  return {
    options: Object.fromEntries(profile.options.map((option) => [option.key, option.default ?? emptyValueOf(option)])),
    resources: { vcpus, ram_mb, disk_gb },
  }
}

export function optionValueLabel(option: ProfileOption, value: unknown): string {
  if (option.type === 'bool') return t(value ? 'guests.form.on' : 'guests.form.off')
  if (option.type === 'secret') return t(value ? 'guests.form.set' : 'guests.form.notSet')
  return value ? String(value) : t('guests.form.none')
}

/** A blank identity value means "chosen at build time", so it is left out of the request, never sent as an empty string. */
export function withoutBlanks(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== ''))
}
