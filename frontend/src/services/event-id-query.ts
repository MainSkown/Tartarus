export const MAX_EVENT_IDS = 50
// The backend refuses a longer query (app/query/limits.py).
export const MAX_QUERY_LENGTH = 2000

const PREFIX = 'event.id:('
const SUFFIX = ')'
const SEPARATOR = ' OR '
// Characters the grammar's value-group token stops at, and the keyword that would end the group.
const NEEDS_QUOTES = /[\s()"\\]|^or$/i
const WILDCARD = /[*?]/

export interface EventIdQuery {
  text: string
  /** How many of the ids the text names; fewer than were given when the cap or the length limit cut it. */
  used: number
}

function asValue(id: string): string {
  return NEEDS_QUOTES.test(id) ? `"${id.replace(/[\\"]/g, '\\$&')}"` : id
}

function textFor(values: string[]): string {
  return `${PREFIX}${values.join(SEPARATOR)}${SUFFIX}`
}

/**
 * A query that matches exactly these events, or `undefined` when none can be named. A wildcard
 * cannot be escaped in the grammar, so an id holding `*` or `?` is left out rather than matching more.
 */
export function eventIdQuery(ids: string[]): EventIdQuery | undefined {
  const values = [...new Set(ids)]
    .filter((id) => id !== '' && !WILDCARD.test(id))
    .slice(0, MAX_EVENT_IDS)
    .map(asValue)
  while (values.length > 0 && textFor(values).length > MAX_QUERY_LENGTH) values.pop()
  return values.length === 0 ? undefined : { text: textFor(values), used: values.length }
}
