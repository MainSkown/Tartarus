export interface SourceField {
  name: string
  value: string
}

// `tartarus.raw` is the original record, shown whole in the raw JSON.
const OMITTED = new Set(['tartarus.raw'])

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function collect(value: unknown, name: string, into: SourceField[]): void {
  if (OMITTED.has(name) || value === null || value === undefined) return
  if (Array.isArray(value)) {
    for (const element of value) collect(element, name, into)
  } else if (isObject(value)) {
    for (const [key, child] of Object.entries(value)) collect(child, name === '' ? key : `${name}.${key}`, into)
  } else {
    into.push({ name, value: String(value) })
  }
}

/** The leaves of a stored event document as dotted ECS field names and text values, in document order. */
export function flattenSource(source: Record<string, unknown>): SourceField[] {
  const fields: SourceField[] = []
  collect(source, '', fields)
  return fields
}
