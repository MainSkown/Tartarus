import { describe, expect, it } from 'vitest'
import { decodeQueryState, encodeQueryState, withQueryState, type QueryUrlState } from '@/services/query-url'

const EMPTY: QueryUrlState = { text: '', chips: [], pids: [], timeRange: null }

describe('decodeQueryState', () => {
  it('reads an empty query as the empty state', () => {
    expect(decodeQueryState({})).toEqual(EMPTY)
  })

  it('reads the applied text from q', () => {
    expect(decodeQueryState({ q: 'process.name:cmd.exe' }).text).toBe('process.name:cmd.exe')
  })

  it('takes the first q when it is repeated', () => {
    expect(decodeQueryState({ q: ['a', 'b'] }).text).toBe('a')
  })

  it('reads one chip per f, negated with a leading dash', () => {
    const { chips } = decodeQueryState({ f: ['process.name:cmd.exe', '-api.name:NtDelayExecution'] })
    expect(chips).toEqual([
      { field: 'process.name', value: 'cmd.exe', negate: false },
      { field: 'api.name', value: 'NtDelayExecution', negate: true },
    ])
  })

  it('reads a single f given as a plain string', () => {
    expect(decodeQueryState({ f: 'lane:network' }).chips).toEqual([{ field: 'lane', value: 'network', negate: false }])
  })

  it('splits a chip on the first colon, so the value keeps its colons', () => {
    expect(decodeQueryState({ f: 'url:http://x/a?b=c' }).chips).toEqual([
      { field: 'url', value: 'http://x/a?b=c', negate: false },
    ])
  })

  it('drops a chip it cannot read: no colon, no field, no value', () => {
    expect(decodeQueryState({ f: ['nocolon', ':value', 'field:', '-', '-:x', ''] }).chips).toEqual([])
  })

  it('keeps the first of two chips on the same field and value', () => {
    const { chips } = decodeQueryState({ f: ['lane:file', 'lane:file', '-lane:file'] })
    expect(chips).toEqual([{ field: 'lane', value: 'file', negate: false }])
  })

  it('reads pids and drops what is not a whole non-negative number', () => {
    expect(decodeQueryState({ pid: ['4120', 'abc', '-3', '1.5', '', '4120', '9708'] }).pids).toEqual([4120, 9708])
    expect(decodeQueryState({ pid: '77' }).pids).toEqual([77])
  })

  it('reads a time range with both ends', () => {
    const range = decodeQueryState({ t: '2026-10-13T12:00:01.250Z..2026-10-13T12:00:04.100Z' }).timeRange
    expect(range).toEqual({ from: '2026-10-13T12:00:01.250Z', to: '2026-10-13T12:00:04.100Z' })
  })

  it('reads a time range with one end empty', () => {
    expect(decodeQueryState({ t: '2026-10-13T12:00:01Z..' }).timeRange).toEqual({ from: '2026-10-13T12:00:01Z', to: null })
    expect(decodeQueryState({ t: '..2026-10-13T12:00:04Z' }).timeRange).toEqual({ from: null, to: '2026-10-13T12:00:04Z' })
  })

  it('drops a time range with no readable end', () => {
    expect(decodeQueryState({ t: '..' }).timeRange).toBeNull()
    expect(decodeQueryState({ t: 'garbage' }).timeRange).toBeNull()
    expect(decodeQueryState({ t: 'x..y' }).timeRange).toBeNull()
  })

  it('keeps the readable end of a half-readable time range', () => {
    expect(decodeQueryState({ t: '2026-10-13T12:00:01Z..nonsense' }).timeRange).toEqual({
      from: '2026-10-13T12:00:01Z',
      to: null,
    })
  })

  it('ignores null entries a router produces for a bare key', () => {
    expect(decodeQueryState({ q: null, f: [null], pid: [null], t: null })).toEqual(EMPTY)
  })
})

describe('encodeQueryState', () => {
  it('encodes the empty state as no params', () => {
    expect(encodeQueryState(EMPTY)).toEqual({})
  })

  it('writes the text, chips, pids and range under their keys', () => {
    expect(
      encodeQueryState({
        text: 'lane:network',
        chips: [
          { field: 'process.name', value: 'cmd.exe', negate: false },
          { field: 'api.name', value: 'NtDelayExecution', negate: true },
        ],
        pids: [4120, 9708],
        timeRange: { from: '2026-10-13T12:00:01Z', to: null },
      }),
    ).toEqual({
      q: 'lane:network',
      f: ['process.name:cmd.exe', '-api.name:NtDelayExecution'],
      pid: ['4120', '9708'],
      t: '2026-10-13T12:00:01Z..',
    })
  })

  it('leaves out a time range with neither end', () => {
    expect(encodeQueryState({ ...EMPTY, timeRange: { from: null, to: null } })).toEqual({})
  })

  it('round-trips awkward values: colons, dashes, dots, spaces and unicode', () => {
    const state: QueryUrlState = {
      text: 'file.path:"C:\\Users\\a b" AND NOT x',
      chips: [
        { field: 'url', value: 'http://x/a?b=c&d=e', negate: false },
        { field: 'file.path', value: '-weird..path with spaces', negate: true },
        { field: 'summary', value: 'zażółć', negate: false },
      ],
      pids: [1],
      timeRange: { from: '2026-10-13T12:00:01.250Z', to: '2026-10-13T12:00:04.100Z' },
    }
    expect(decodeQueryState(encodeQueryState(state))).toEqual(state)
  })
})

describe('withQueryState', () => {
  it('replaces only its own params and keeps the others', () => {
    const merged = withQueryState(
      { q: 'old', f: 'lane:file', pid: '1', t: '..2026-10-13T12:00:04Z', tab: 'x', other: ['a', 'b'] },
      { ...EMPTY, text: 'new' },
    )
    expect(merged).toEqual({ tab: 'x', other: ['a', 'b'], q: 'new' })
  })
})
