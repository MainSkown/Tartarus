import { describe, expect, it } from 'vitest'
import type { QueryErrorRead } from '@/api'
import { applyErrorSuggestion, underlineSegments } from '@/services/query-underline'

function error(start: number, end: number, message = 'bad', suggestion: string | null = null): QueryErrorRead {
  return { start, end, message, suggestion }
}

const texts = (segments: { text: string }[]) => segments.map((segment) => segment.text)
const flagged = (segments: { text: string; error?: QueryErrorRead }[]) =>
  segments.filter((segment) => segment.error).map((segment) => segment.text)

describe('underlineSegments', () => {
  it('is one plain segment when there are no errors', () => {
    expect(underlineSegments('lane:file', [])).toEqual([{ text: 'lane:file' }])
  })

  it('is no segment for empty text', () => {
    expect(underlineSegments('', [])).toEqual([])
    expect(underlineSegments('', [error(0, 3)])).toEqual([])
  })

  it('splits around one error span, keeping the error on the flagged part', () => {
    const bad = error(4, 8, 'unknown field')
    expect(underlineSegments('a b prcs:x', [bad])).toEqual([
      { text: 'a b ' },
      { text: 'prcs', error: bad },
      { text: ':x' },
    ])
  })

  it('handles an error at the very start and at the very end', () => {
    expect(texts(underlineSegments('abcdef', [error(0, 2)]))).toEqual(['ab', 'cdef'])
    expect(texts(underlineSegments('abcdef', [error(4, 6)]))).toEqual(['abcd', 'ef'])
  })

  it('handles an error over the whole text', () => {
    expect(flagged(underlineSegments('abc', [error(0, 3)]))).toEqual(['abc'])
  })

  it('handles two separate errors in order', () => {
    expect(flagged(underlineSegments('aa bb cc dd', [error(0, 2), error(6, 8)]))).toEqual(['aa', 'cc'])
  })

  it('orders errors that were given out of order', () => {
    expect(texts(underlineSegments('aa bb cc', [error(6, 8), error(0, 2)]))).toEqual(['aa', ' bb ', 'cc'])
  })

  it('clamps a span that runs past the end of the text', () => {
    expect(underlineSegments('abc', [error(1, 99)])).toEqual([
      { text: 'a' },
      { text: 'bc', error: error(1, 99) },
    ])
  })

  it('drops a span that starts past the end of the text', () => {
    expect(underlineSegments('abc', [error(10, 12)])).toEqual([{ text: 'abc' }])
  })

  it('clamps a negative start to zero', () => {
    expect(flagged(underlineSegments('abc', [error(-3, 2)]))).toEqual(['ab'])
  })

  it('widens an empty span to the character at it', () => {
    expect(flagged(underlineSegments('abc', [error(1, 1)]))).toEqual(['b'])
  })

  it('widens an empty span at the end of the text to the last character', () => {
    expect(flagged(underlineSegments('abc', [error(3, 3)]))).toEqual(['c'])
  })

  it('gives the overlapped stretch to the earlier error and keeps the rest of the later one', () => {
    const first = error(0, 4, 'first')
    const second = error(2, 6, 'second')
    expect(underlineSegments('abcdefgh', [first, second])).toEqual([
      { text: 'abcd', error: first },
      { text: 'ef', error: second },
      { text: 'gh' },
    ])
  })

  it('drops an error that lies wholly inside an earlier one', () => {
    const outer = error(0, 6, 'outer')
    expect(underlineSegments('abcdefgh', [outer, error(2, 4, 'inner')])).toEqual([
      { text: 'abcdef', error: outer },
      { text: 'gh' },
    ])
  })

  it('treats two errors on the same span as one', () => {
    const first = error(1, 3, 'first')
    expect(underlineSegments('abcd', [first, error(1, 3, 'second')])).toEqual([
      { text: 'a' },
      { text: 'bc', error: first },
      { text: 'd' },
    ])
  })

  it('keeps adjacent errors as separate segments', () => {
    expect(flagged(underlineSegments('abcd', [error(0, 2), error(2, 4)]))).toEqual(['ab', 'cd'])
  })

  it('always gives back the text it was given, whatever the spans', () => {
    const text = 'process.name:"a b" AND (x OR y'
    const spans = [error(-5, 3), error(2, 9), error(9, 9), error(20, 500), error(7, 7), error(999, 1000)]
    expect(texts(underlineSegments(text, spans)).join('')).toBe(text)
  })

  it('never makes an empty segment', () => {
    const segments = underlineSegments('abcdef', [error(0, 2), error(2, 2), error(5, 9)])
    expect(segments.every((segment) => segment.text.length > 0)).toBe(true)
  })
})

describe('applyErrorSuggestion', () => {
  it('replaces the error span with the suggestion', () => {
    expect(applyErrorSuggestion('lane:x AND prcess:cmd', error(11, 17, 'unknown', 'process'))).toBe(
      'lane:x AND process:cmd',
    )
  })

  it('leaves the text alone for an error with no suggestion', () => {
    expect(applyErrorSuggestion('abc', error(0, 1))).toBe('abc')
  })

  it('clamps a span that runs past the end', () => {
    expect(applyErrorSuggestion('ab prc', error(3, 40, 'unknown', 'process'))).toBe('ab process')
  })
})
