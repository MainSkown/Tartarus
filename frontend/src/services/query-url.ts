import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import type { FilterChip } from '@/api'

export interface QueryTimeRange {
  from: string | null
  to: string | null
}

/** The part of the shared query state that lives in the URL; `eventId` is the event open in the detail drawer. */
export interface QueryUrlState {
  text: string
  chips: FilterChip[]
  pids: number[]
  timeRange: QueryTimeRange | null
  eventId: string | null
}

const TEXT_KEY = 'q'
const CHIP_KEY = 'f'
const PID_KEY = 'pid'
const TIME_KEY = 't'
const EVENT_KEY = 'e'
const OWN_KEYS = [TEXT_KEY, CHIP_KEY, PID_KEY, TIME_KEY, EVENT_KEY]
const NEGATION_PREFIX = '-'
const CHIP_SEPARATOR = ':'
const RANGE_SEPARATOR = '..'

type RawValue = string | null | undefined | (string | null | undefined)[]

function allOf(value: RawValue): string[] {
  const list = Array.isArray(value) ? value : [value]
  return list.filter((entry): entry is string => typeof entry === 'string')
}

function parseChip(raw: string): FilterChip | undefined {
  const negate = raw.startsWith(NEGATION_PREFIX)
  const body = negate ? raw.slice(NEGATION_PREFIX.length) : raw
  const split = body.indexOf(CHIP_SEPARATOR)
  if (split <= 0 || split === body.length - 1) return undefined
  return { field: body.slice(0, split), value: body.slice(split + 1), negate }
}

/** Two chips on the same field and value are one filter, whichever way each points. */
export function isSameFilter(a: FilterChip, b: FilterChip): boolean {
  return a.field === b.field && a.value === b.value
}

function decodeChips(value: RawValue): FilterChip[] {
  const chips: FilterChip[] = []
  for (const raw of allOf(value)) {
    const chip = parseChip(raw)
    if (chip && !chips.some((known) => isSameFilter(known, chip))) chips.push(chip)
  }
  return chips
}

function decodePids(value: RawValue): number[] {
  const pids = allOf(value)
    .filter((raw) => /^\d+$/.test(raw))
    .map(Number)
    .filter(Number.isSafeInteger)
  return [...new Set(pids)]
}

function readableInstant(raw: string): string | null {
  return raw !== '' && !Number.isNaN(Date.parse(raw)) ? raw : null
}

function decodeTimeRange(value: RawValue): QueryTimeRange | null {
  const [raw] = allOf(value)
  const split = raw?.indexOf(RANGE_SEPARATOR) ?? -1
  if (raw === undefined || split < 0) return null
  const from = readableInstant(raw.slice(0, split))
  const to = readableInstant(raw.slice(split + RANGE_SEPARATOR.length))
  return from === null && to === null ? null : { from, to }
}

/** Reads the shared query state from a route's query; whatever cannot be read is dropped, never thrown. */
export function decodeQueryState(query: LocationQuery | Record<string, RawValue>): QueryUrlState {
  const [text = ''] = allOf(query[TEXT_KEY])
  const [eventId] = allOf(query[EVENT_KEY])
  return {
    text,
    chips: decodeChips(query[CHIP_KEY]),
    pids: decodePids(query[PID_KEY]),
    timeRange: decodeTimeRange(query[TIME_KEY]),
    eventId: eventId || null,
  }
}

function encodeChip({ field, value, negate }: FilterChip): string {
  return `${negate ? NEGATION_PREFIX : ''}${field}${CHIP_SEPARATOR}${value}`
}

/** The query params of a state; params for an empty part are left out. */
export function encodeQueryState(state: QueryUrlState): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {}
  if (state.text !== '') params[TEXT_KEY] = state.text
  if (state.chips.length > 0) params[CHIP_KEY] = state.chips.map(encodeChip)
  if (state.pids.length > 0) params[PID_KEY] = state.pids.map(String)
  const { timeRange } = state
  if (timeRange && (timeRange.from !== null || timeRange.to !== null)) {
    params[TIME_KEY] = `${timeRange.from ?? ''}${RANGE_SEPARATOR}${timeRange.to ?? ''}`
  }
  if (state.eventId !== null) params[EVENT_KEY] = state.eventId
  return params
}

/** `query` with this module's params replaced by the state's, every other param kept. */
export function withQueryState(query: LocationQuery | LocationQueryRaw, state: QueryUrlState): LocationQueryRaw {
  const others = Object.fromEntries(Object.entries(query).filter(([key]) => !OWN_KEYS.includes(key)))
  return { ...others, ...encodeQueryState(state) }
}
