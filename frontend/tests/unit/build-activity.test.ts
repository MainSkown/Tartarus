import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { STALE_AFTER_S, activityAgeSeconds, activityNotice } from '@/services/build-activity'

const NOW = new Date('2026-10-21T12:10:00Z')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => vi.useRealTimers())

describe('activityAgeSeconds', () => {
  it('counts the seconds since the time given', () => {
    expect(activityAgeSeconds('2026-10-21T12:09:48Z', NOW.getTime())).toBe(12)
  })

  it('has no age for a build that has shown no activity yet, or a time it cannot read', () => {
    expect(activityAgeSeconds(null, NOW.getTime())).toBeUndefined()
    expect(activityAgeSeconds(undefined, NOW.getTime())).toBeUndefined()
    expect(activityAgeSeconds('yesterday-ish', NOW.getTime())).toBeUndefined()
  })

  it('never goes negative when the service clock runs ahead of the browser', () => {
    expect(activityAgeSeconds('2026-10-21T12:10:03Z', NOW.getTime())).toBe(0)
  })
})

describe('activityNotice', () => {
  it('says how long ago the last activity was, in the usual duration format', () => {
    expect(activityNotice(12)).toEqual({ text: 'last activity 12s ago', stale: false })
    expect(activityNotice(95)).toEqual({ text: 'last activity 1m 35s ago', stale: false })
  })

  it('turns to a warning once two minutes pass without news, naming the minutes', () => {
    expect(STALE_AFTER_S).toBe(120)
    expect(activityNotice(STALE_AFTER_S - 1).stale).toBe(false)
    expect(activityNotice(STALE_AFTER_S)).toEqual({ text: 'no news for 2 min: the step may be waiting or stuck', stale: true })
    expect(activityNotice(3 * 60 + 59).text).toBe('no news for 3 min: the step may be waiting or stuck')
  })
})
