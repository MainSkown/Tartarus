import type { IocType, RegistryChange } from '@/api'

export interface EventsFilter {
  field: string
  value: string | number
  negate?: boolean
}

/** What a "show events" action does to the shared query before opening the Events tab. */
export type EventsTarget = { chips: EventsFilter[] } | { pid: number } | { text: string }

type Missing = null | undefined | ''

const DOMAIN_ALIAS = 'domain'

export function filterOn(field: string, value: string | number | Missing): EventsFilter[] {
  return value === null || value === undefined || value === '' ? [] : [{ field, value }]
}

export function flowDestinationFilters(ip: string | null, port: number | null): EventsFilter[] {
  return ip === null ? [] : [...filterOn('destination.ip', ip), ...filterOn('destination.port', port)]
}

/** `domain` is the catalog's alias for the DNS name and the destination domain together. */
export function hostEntryFilters(kind: string, host: string): EventsFilter[] {
  return filterOn(kind === 'ip' ? 'destination.ip' : DOMAIN_ALIAS, host)
}

const IOC_FIELDS: Partial<Record<IocType, string>> = {
  domain: DOMAIN_ALIAS,
  ip: 'destination.ip',
  url: 'url.full',
  hash: 'file.hash.sha256',
  file: 'file.path',
  registry: 'registry.path',
}

/** A mutex has no event field to filter on, so it has no filter. */
export function iocFilters(type: IocType, value: string): EventsFilter[] {
  const field = IOC_FIELDS[type]
  return field === undefined ? [] : filterOn(field, value)
}

/**
 * The hive, key and value the registry view grouped the change by. `registry.path` is not used:
 * it is the raw path as captured, which names the hive differently and ends in the value name.
 */
export function registryChangeFilters({
  hive,
  key,
  value_name,
}: Pick<RegistryChange, 'value_name'> & { hive: string | null; key: string }): EventsFilter[] {
  return [
    ...filterOn('registry.hive', hive),
    ...filterOn('registry.key', key),
    ...filterOn('registry.value', value_name),
  ]
}

function describeFilter({ field, value, negate }: EventsFilter): string {
  return `${negate ? 'NOT ' : ''}${field}: ${value}`
}

export function describeTarget(target: EventsTarget): string {
  if ('pid' in target) return `pid: ${target.pid}`
  if ('text' in target) return `query: ${target.text}`
  return target.chips.map(describeFilter).join(' and ')
}
