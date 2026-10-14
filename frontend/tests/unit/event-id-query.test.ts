import { describe, expect, it } from 'vitest'
import { MAX_EVENT_IDS, MAX_QUERY_LENGTH, eventIdQuery } from '@/services/event-id-query'

const ids = (count: number, length = 40) => Array.from({ length: count }, (_, i) => String(i).padStart(length, 'a'))

describe('eventIdQuery', () => {
  it('is an alternative group over the ids', () => {
    expect(eventIdQuery(['3f78', 'ab12'])).toEqual({ text: 'event.id:(3f78 OR ab12)', used: 2 })
  })

  it('is one id in a group too', () => {
    expect(eventIdQuery(['3f78'])).toEqual({ text: 'event.id:(3f78)', used: 1 })
  })

  it('is nothing for no ids', () => {
    expect(eventIdQuery([])).toBeUndefined()
  })

  it('leaves slashes, colons and hyphens bare, the grammar takes them in a value group', () => {
    expect(eventIdQuery(['capemon/1:2-3'])?.text).toBe('event.id:(capemon/1:2-3)')
  })

  it.each([
    ['has a space', 'a b', '"a b"'],
    ['has a parenthesis', 'a(b)', '"a(b)"'],
    ['has a quote', 'a"b', '"a\\"b"'],
    ['has a backslash', 'a\\b', '"a\\\\b"'],
    ['is the word or', 'oR', '"oR"'],
  ])('quotes an id that %s', (_why, id, quoted) => {
    expect(eventIdQuery([id])?.text).toBe(`event.id:(${quoted})`)
  })

  it('keeps an id that only contains the word or', () => {
    expect(eventIdQuery(['order'])?.text).toBe('event.id:(order)')
  })

  it.each(['a*', 'a?b'])('leaves out %s, a wildcard cannot be escaped and would match other events', (id) => {
    expect(eventIdQuery(['x', id])).toEqual({ text: 'event.id:(x)', used: 1 })
  })

  it('is nothing when every id is left out', () => {
    expect(eventIdQuery(['a*'])).toBeUndefined()
  })

  it('names each id once', () => {
    expect(eventIdQuery(['a', 'b', 'a'])).toEqual({ text: 'event.id:(a OR b)', used: 2 })
  })

  it('takes at most the first 50 ids', () => {
    const query = eventIdQuery(ids(80, 8))!
    expect(query.used).toBe(MAX_EVENT_IDS)
    expect(query.text.split(' OR ')).toHaveLength(MAX_EVENT_IDS)
    expect(query.text).toContain(ids(80, 8)[49]!)
    expect(query.text).not.toContain(ids(80, 8)[50]!)
  })

  it('takes fewer ids when the text would pass the query length limit', () => {
    const long = ids(50, 80)
    const query = eventIdQuery(long)!
    expect(query.text.length).toBeLessThanOrEqual(MAX_QUERY_LENGTH)
    expect(query.used).toBeLessThan(50)
    const oneMore = `event.id:(${long.slice(0, query.used + 1).join(' OR ')})`
    expect(oneMore.length).toBeGreaterThan(MAX_QUERY_LENGTH)
  })

  it('is nothing when even the first id does not fit', () => {
    expect(eventIdQuery(['x'.repeat(MAX_QUERY_LENGTH)])).toBeUndefined()
  })
})
