import type { AnalysisPhase, AnalysisStatus } from '@/api'
import { ANALYSIS_STATUSES } from '@/services/analysis-status'

export interface LiveStatus {
  status: AnalysisStatus
  phase: AnalysisPhase
  elapsed_s: number | null
  remaining_s: number | null
}

export interface LiveProcessNode {
  pid: number
  ppid: number | null
  name: string | null
  executable: string | null
  command_line: string | null
  start: string | null
  end: string | null
}

export type ProcessOp = 'add' | 'update' | 'end'

export interface ProcessDelta {
  op: ProcessOp
  node: LiveProcessNode
}

/** The fields of an ECS event document the LIVE tab reads; the server sends more. */
export interface LiveEvent {
  '@timestamp': string
  event: { id: string; action?: string; sequence?: number; severity?: number }
  tartarus: { lane: string; summary: string }
  process?: { pid?: number; name?: string | null }
}

export interface LiveCounts {
  by_lane: Record<string, number>
  by_severity: Record<string, number>
  total: number
}

export interface LiveError {
  code: string
  message: string
}

interface Envelope<Type extends string, Data> {
  type: Type
  ts: string
  data: Data
}

export type LiveMessage =
  | Envelope<'status', LiveStatus>
  | Envelope<'events', { events: LiveEvent[]; dropped: number }>
  | Envelope<'process', ProcessDelta>
  | Envelope<'counts', LiveCounts>
  | Envelope<'phase', { phase: 'final' }>
  | Envelope<'error', LiveError>
  | Envelope<'pong', Record<string, never>>

/** What the server filters the stream by; an absent list means "all". */
export interface LiveSubscription {
  lanes?: string[]
  pids?: number[]
  include_api?: boolean
}

export type LiveClientMessage = { type: 'subscribe'; data: LiveSubscription } | { type: 'ping'; data: Record<string, never> }

type Json = Record<string, unknown>

const PROCESS_OPS: readonly string[] = ['add', 'update', 'end']
const PHASES: readonly string[] = ['live', 'final']

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const isString = (value: unknown): value is string => typeof value === 'string'
const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const isNumberOrNull = (value: unknown): value is number | null => value === null || isNumber(value)

function stringOrNull(value: unknown): string | null {
  return isString(value) ? value : null
}

function isNumberMap(value: unknown): value is Record<string, number> {
  return isObject(value) && Object.values(value).every(isNumber)
}

function parseStatus(data: Json): LiveStatus | undefined {
  const { status, phase, elapsed_s, remaining_s } = data
  if (!isString(status) || !(ANALYSIS_STATUSES as string[]).includes(status)) return undefined
  if (!isString(phase) || !PHASES.includes(phase)) return undefined
  if (!isNumberOrNull(elapsed_s) || !isNumberOrNull(remaining_s)) return undefined
  return { status: status as AnalysisStatus, phase: phase as AnalysisPhase, elapsed_s, remaining_s }
}

function parseEvent(raw: unknown): LiveEvent | undefined {
  if (!isObject(raw) || !isString(raw['@timestamp']) || !isObject(raw.event) || !isObject(raw.tartarus)) return undefined
  if (!isString(raw.event.id) || !isString(raw.tartarus.lane) || !isString(raw.tartarus.summary)) return undefined
  return raw as unknown as LiveEvent
}

function parseEvents(data: Json): Extract<LiveMessage, { type: 'events' }>['data'] | undefined {
  if (!Array.isArray(data.events)) return undefined
  const events = data.events.map(parseEvent).filter((event): event is LiveEvent => event !== undefined)
  return { events, dropped: isNumber(data.dropped) ? data.dropped : 0 }
}

function parseProcessNode(raw: unknown): LiveProcessNode | undefined {
  if (!isObject(raw) || !isNumber(raw.pid)) return undefined
  return {
    pid: raw.pid,
    ppid: isNumber(raw.ppid) ? raw.ppid : null,
    name: stringOrNull(raw.name),
    executable: stringOrNull(raw.executable),
    command_line: stringOrNull(raw.command_line),
    start: stringOrNull(raw.start),
    end: stringOrNull(raw.end),
  }
}

function parseProcess(data: Json): ProcessDelta | undefined {
  const node = parseProcessNode(data.node)
  if (!isString(data.op) || !PROCESS_OPS.includes(data.op) || node === undefined) return undefined
  return { op: data.op as ProcessOp, node }
}

function parseCounts(data: Json): LiveCounts | undefined {
  const { by_lane, by_severity, total } = data
  if (!isNumberMap(by_lane) || !isNumberMap(by_severity) || !isNumber(total)) return undefined
  return { by_lane, by_severity, total }
}

function parseError(data: Json): LiveError | undefined {
  return isString(data.code) && isString(data.message) ? { code: data.code, message: data.message } : undefined
}

/**
 * Validates one server message of `WS /ws/analyses/{id}/live` at runtime. The server's JSON is not
 * trusted with a cast: anything unknown or malformed returns `undefined` and is ignored, never thrown.
 */
export function parseLiveMessage(raw: unknown): LiveMessage | undefined {
  if (!isObject(raw) || !isString(raw.type) || !isString(raw.ts) || !isObject(raw.data)) return undefined
  const { type, ts, data } = raw
  switch (type) {
    case 'status': {
      const parsed = parseStatus(data)
      return parsed && { type, ts, data: parsed }
    }
    case 'events': {
      const parsed = parseEvents(data)
      return parsed && { type, ts, data: parsed }
    }
    case 'process': {
      const parsed = parseProcess(data)
      return parsed && { type, ts, data: parsed }
    }
    case 'counts': {
      const parsed = parseCounts(data)
      return parsed && { type, ts, data: parsed }
    }
    case 'phase':
      return data.phase === 'final' ? { type, ts, data: { phase: 'final' } } : undefined
    case 'error': {
      const parsed = parseError(data)
      return parsed && { type, ts, data: parsed }
    }
    case 'pong':
      return { type, ts, data: {} }
    default:
      return undefined
  }
}
