import type { Event, FieldRead, JsonValue } from '@/api'

type Reader = (event: Event) => string | number | null | undefined

// What the typed `Event` carries, used when the search did not return a column (the default columns
// are on every row already, so choosing one of them needs no `columns` round trip to show).
const TYPED_READERS: Record<string, Reader> = {
  '@timestamp': (event) => event.time,
  'event.id': (event) => event.id,
  'event.sequence': (event) => event.sequence,
  'event.kind': (event) => event.kind,
  'event.category': (event) => event.category.join(', '),
  'event.action': (event) => event.action,
  'event.module': (event) => event.module,
  'event.dataset': (event) => event.dataset,
  'tartarus.lane': (event) => event.lane,
  'tartarus.summary': (event) => event.summary,
  'process.pid': (event) => event.process?.pid,
  'process.name': (event) => event.process?.name,
  'process.entity_id': (event) => event.process?.entity_id,
  'api.name': (event) => event.api_name,
  'rule.name': (event) => event.rule_name,
  'rule.ruleset': (event) => event.rule_ruleset,
  'destination.ip': (event) => event.destination?.ip,
  'destination.port': (event) => event.destination?.port,
  'destination.domain': (event) => event.destination?.domain,
  'dns.question.name': (event) => event.dns_query,
  'url.full': (event) => event.url,
  'file.path': (event) => event.file_path,
  'registry.path': (event) => event.registry_path,
}

/** The most columns a search can be asked for (the API's limit). */
export const MAX_COLUMNS = 12

/** The catalog fields the chooser offers: every searchable field that is not a composite alias. */
export function offeredColumnFields(catalog: FieldRead[]): FieldRead[] {
  return catalog.filter((field) => field.searchable && field.members.length === 0)
}

function formatValue(value: JsonValue | undefined): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map(formatValue).join(', ')
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, entry]) => `${key}=${typeof entry === 'object' && entry !== null ? JSON.stringify(entry) : formatValue(entry)}`)
      .join(', ')
  }
  return String(value)
}

/** The text a cell shows for a field: the value the search returned, else the typed event's; empty when there is none. */
export function columnValue(event: Event, field: string): string {
  if (field in event.fields) return formatValue(event.fields[field])
  return formatValue(TYPED_READERS[field]?.(event))
}

const COMMON_GROUP = 'common'

export interface ColumnFieldGroup {
  name: string
  fields: FieldRead[]
}

/** Fields grouped by what precedes their first dot, in catalog order, narrowed to those matching `search`. */
export function columnFieldGroups(fields: FieldRead[], search: string): ColumnFieldGroup[] {
  const needle = search.trim().toLowerCase()
  const groups = new Map<string, FieldRead[]>()
  for (const field of fields) {
    if (needle !== '' && !`${field.name} ${field.description}`.toLowerCase().includes(needle)) continue
    const [first, ...rest] = field.name.split('.')
    const name = rest.length === 0 ? COMMON_GROUP : first!
    groups.set(name, [...(groups.get(name) ?? []), field])
  }
  return [...groups].map(([name, grouped]) => ({ name, fields: grouped }))
}
