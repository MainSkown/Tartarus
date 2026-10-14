import type { QueryTimeRange } from '@/services/query-url'

/** Stands for a range with no event in it, which the API reads as an empty lane list: it matches nothing. */
export const NO_EVENTS = 'no-events'

/** A time range that takes the place of the shared query state's for the events table (the Timeline tab's visible range). */
export type RangeOverride = QueryTimeRange | typeof NO_EVENTS
