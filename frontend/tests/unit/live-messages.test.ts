import { describe, expect, it } from 'vitest'
import { parseLiveMessage } from '@/services/live-messages'
import { liveEvent, message } from './live-fixtures'

const STATUS = { status: 'running', phase: 'live', elapsed_s: 12.5, remaining_s: 167.5 }

describe('parseLiveMessage', () => {
  it('accepts a status message', () => {
    expect(parseLiveMessage(message('status', STATUS))).toEqual({ type: 'status', ts: expect.any(String), data: STATUS })
  })

  it('accepts a status with no timing, as a queued analysis sends it', () => {
    const data = { status: 'queued', phase: 'live', elapsed_s: null, remaining_s: null }
    expect(parseLiveMessage(message('status', data))?.data).toEqual(data)
  })

  it.each([
    ['an unknown status', { ...STATUS, status: 'paused' }],
    ['an unknown phase', { ...STATUS, phase: 'later' }],
    ['a text elapsed time', { ...STATUS, elapsed_s: 'soon' }],
    ['a missing remaining time', { status: 'running', phase: 'live', elapsed_s: 1 }],
  ])('ignores a status with %s', (_name, data) => {
    expect(parseLiveMessage(message('status', data))).toBeUndefined()
  })

  it('accepts events with the dropped count', () => {
    const events = [liveEvent({ id: 'a' }), liveEvent({ id: 'b', lane: 'api' })]
    const parsed = parseLiveMessage(message('events', { events, dropped: 7 }))
    expect(parsed).toEqual({ type: 'events', ts: expect.any(String), data: { events, dropped: 7 } })
  })

  it('treats a missing dropped count as zero', () => {
    const parsed = parseLiveMessage(message('events', { events: [] }))
    expect(parsed?.type === 'events' && parsed.data.dropped).toBe(0)
  })

  it('keeps the events that are well formed and skips the ones that are not', () => {
    const good = liveEvent({ id: 'good' })
    const noLane = { ...liveEvent({ id: 'bad' }), tartarus: { summary: 'x' } }
    const noId = { ...liveEvent(), event: {} }
    const parsed = parseLiveMessage(message('events', { events: [noLane, good, noId, 'text', null], dropped: 0 }))
    expect(parsed?.type === 'events' && parsed.data.events).toEqual([good])
  })

  it('ignores events whose list is not a list', () => {
    expect(parseLiveMessage(message('events', { events: 'many', dropped: 0 }))).toBeUndefined()
  })

  it.each(['add', 'update', 'end'])('accepts a process %s with its fields', (op) => {
    const node = { pid: 4, ppid: 1, name: 'a.exe', executable: 'C:\\a.exe', command_line: 'a.exe', start: '2026-10-13T15:39:50Z', end: null }
    expect(parseLiveMessage(message('process', { op, node }))?.data).toEqual({ op, node })
  })

  it('fills the fields a process node leaves out with null', () => {
    const parsed = parseLiveMessage(message('process', { op: 'add', node: { pid: 4 } }))
    expect(parsed?.type === 'process' && parsed.data.node).toEqual({
      pid: 4,
      ppid: null,
      name: null,
      executable: null,
      command_line: null,
      start: null,
      end: null,
    })
  })

  it.each([
    ['an unknown op', { op: 'rename', node: { pid: 4 } }],
    ['a node without a pid', { op: 'add', node: { name: 'a.exe' } }],
    ['no node', { op: 'add' }],
    ['a text pid', { op: 'add', node: { pid: '4' } }],
  ])('ignores a process message with %s', (_name, data) => {
    expect(parseLiveMessage(message('process', data))).toBeUndefined()
  })

  it('accepts counts', () => {
    const data = { by_lane: { file: 3, api: 90 }, by_severity: { info: 93, low: 0, medium: 0, high: 0, critical: 0 }, total: 93 }
    expect(parseLiveMessage(message('counts', data))?.data).toEqual(data)
  })

  it('ignores counts whose lane map holds a non-number', () => {
    const data = { by_lane: { file: 'three' }, by_severity: {}, total: 3 }
    expect(parseLiveMessage(message('counts', data))).toBeUndefined()
  })

  it('accepts the final phase and ignores any other', () => {
    expect(parseLiveMessage(message('phase', { phase: 'final' }))?.type).toBe('phase')
    expect(parseLiveMessage(message('phase', { phase: 'live' }))).toBeUndefined()
  })

  it('accepts an error and a pong', () => {
    expect(parseLiveMessage(message('error', { code: 'log_format', message: 'unknown record' }))?.data).toEqual({
      code: 'log_format',
      message: 'unknown record',
    })
    expect(parseLiveMessage(message('pong', {}))?.type).toBe('pong')
  })

  it('ignores an error with no message', () => {
    expect(parseLiveMessage(message('error', { code: 'log_format' }))).toBeUndefined()
  })

  it.each([
    ['text', 'hello'],
    ['null', null],
    ['an unknown type', message('detection', {})],
    ['no type', { ts: '2026-10-13T15:39:50Z', data: {} }],
    ['no data', { type: 'status', ts: '2026-10-13T15:39:50Z' }],
    ['no timestamp', { type: 'pong', data: {} }],
  ])('ignores %s without throwing', (_name, raw) => {
    expect(() => parseLiveMessage(raw)).not.toThrow()
    expect(parseLiveMessage(raw)).toBeUndefined()
  })
})
