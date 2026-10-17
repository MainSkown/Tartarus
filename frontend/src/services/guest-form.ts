import type { GuestProfile, GuestResources, IdentityRule, ProfileOption } from '@/api'

export const BLANK_IDENTITY_LABEL = 'chosen at build time'

export const NAME_RULE = 'Use 2 to 32 lower-case letters, digits or hyphens, starting with a letter'
const GUEST_NAME = /^[a-z][a-z0-9-]{1,31}$/

export type OptionValues = Record<string, unknown>
export type ResourceField = keyof GuestResources
export type ResourceProblems = Partial<Record<ResourceField, string>>

export interface ProfileDefaults {
  options: OptionValues
  resources: GuestResources
}

export function guestNameProblem(name: string, taken: readonly string[]): string | undefined {
  if (!GUEST_NAME.test(name)) return NAME_RULE
  return taken.includes(name) ? `Another guest is already called ${name}` : undefined
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
  if (fullMatch(rule.pattern)?.test(value) === false) return `${rule.label} must match ${rule.pattern}`
  const reserved = (rule.reserved ?? []).some((name) => name.toLowerCase() === value.toLowerCase())
  return reserved ? `${value} is reserved` : undefined
}

export function resourceProblems(resources: GuestResources, minDiskGb: number): ResourceProblems {
  const problems: ResourceProblems = {}
  for (const field of ['vcpus', 'ram_mb', 'disk_gb'] as const) {
    if (!Number.isInteger(resources[field]) || resources[field] < 1) problems[field] = 'A whole number of at least 1'
  }
  if (!problems.disk_gb && resources.disk_gb < minDiskGb) problems.disk_gb = `At least ${minDiskGb} GB`
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
  if (option.type === 'bool') return value ? 'ON' : 'OFF'
  if (option.type === 'secret') return value ? 'set' : 'not set'
  return value ? String(value) : 'none'
}

/** A blank identity value means "chosen at build time", so it is left out of the request, never sent as an empty string. */
export function withoutBlanks(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== ''))
}
