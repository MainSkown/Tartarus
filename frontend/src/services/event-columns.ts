import type { Event, FieldRead } from '@/api'

type Reader = (event: Event) => string | number | null | undefined

// The fields a row of the table can show beyond its default columns: exactly what the typed `Event`
// carries. A catalog field missing here would need `GET events/{id}` per row, so it is not offered.
const EXTRA_COLUMN_READERS: Record<string, Reader> = {
  'event.id': (event) => event.id,
  'event.sequence': (event) => event.sequence,
  'event.kind': (event) => event.kind,
  'event.category': (event) => event.category.join(', '),
  'event.module': (event) => event.module,
  'event.dataset': (event) => event.dataset,
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

export function isExtraColumn(field: string): boolean {
  return field in EXTRA_COLUMN_READERS
}

/** The catalog fields the chooser offers: searchable, not a composite alias, and carried by the event. */
export function offeredColumnFields(catalog: FieldRead[]): FieldRead[] {
  return catalog.filter((field) => field.searchable && field.members.length === 0 && isExtraColumn(field.name))
}

/** The text a cell shows for a field; empty when the event has no value for it. */
export function columnValue(event: Event, field: string): string {
  const value = EXTRA_COLUMN_READERS[field]?.(event)
  return value === null || value === undefined ? '' : String(value)
}

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
    const name = field.name.split('.')[0]!
    groups.set(name, [...(groups.get(name) ?? []), field])
  }
  return [...groups].map(([name, grouped]) => ({ name, fields: grouped }))
}
