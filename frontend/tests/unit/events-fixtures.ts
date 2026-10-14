import type { Event, EventDetail, EventPage, Facet, FacetsResponse } from '@/api'

export function eventFixture(overrides: Partial<Event> & { id: string }): Event {
  return {
    time: '2026-10-13T15:39:33.863Z',
    sequence: 1,
    lane: 'process',
    kind: 'event',
    category: ['process'],
    action: 'process-created',
    module: 'capemon',
    dataset: 'capemon.process',
    summary: 'cmd.exe started powershell.exe',
    severity: null,
    process: { pid: 2476, name: 'cmd.exe', entity_id: '45:2476@1760370000' },
    api_name: null,
    rule_name: null,
    rule_ruleset: null,
    destination: null,
    dns_query: null,
    url: null,
    file_path: null,
    registry_path: null,
    fields: {},
    ...overrides,
  }
}

/** `count` events with ids `e1`, `e2`, ... one second apart. */
export function eventList(count: number, firstNumber = 1): Event[] {
  return Array.from({ length: count }, (_, index) => {
    const number = firstNumber + index
    return eventFixture({
      id: `e${number}`,
      sequence: number,
      time: new Date(Date.UTC(2026, 9, 13, 15, 39, 33 + number, 123)).toISOString(),
      summary: `summary of event ${number}`,
    })
  })
}

export function eventPage(events: Event[], overrides: Partial<EventPage> = {}): EventPage {
  return { events, total: events.length, next_cursor: null, ...overrides }
}

export function facetFixture(field: string, values: [string, number][]): Facet {
  return { field, values: values.map(([value, count]) => ({ value, count })), total: values.reduce((sum, [, count]) => sum + count, 0) }
}

export function facetsResponse(facets: Facet[]): FacetsResponse {
  return { facets }
}

export function eventDetail(event: Event, overrides: Partial<EventDetail> = {}): EventDetail {
  return {
    event,
    source: { '@timestamp': event.time, event: { id: event.id, action: event.action }, tartarus: { summary: event.summary, raw: { x: 1 } } },
    related: { references: { items: [], total: 0 }, referenced_by: { items: [], total: 0 } },
    ...overrides,
  }
}
