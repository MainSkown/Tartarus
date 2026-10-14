import { describe, expect, it } from 'vitest'
import type { Event } from '@/api'
import { pidNamesOf } from '@/services/pid-names'

const eventOf = (process: { pid: number; name: string | null } | null) => ({ process }) as Event

describe('pidNamesOf', () => {
  it('names each wanted pid by the first event that carries its name', () => {
    const events = [eventOf({ pid: 4, name: 'cmd.exe' }), eventOf({ pid: 9, name: 'a.exe' }), eventOf({ pid: 4, name: 'other' })]
    expect(pidNamesOf(events, [4, 9])).toEqual({ 4: 'cmd.exe', 9: 'a.exe' })
  })

  it('leaves out a pid no event names, and one nobody asked for', () => {
    const events = [eventOf({ pid: 4, name: null }), eventOf(null), eventOf({ pid: 5, name: 'x.exe' }), eventOf({ pid: 4, name: 'later.exe' })]
    expect(pidNamesOf(events, [4, 6])).toEqual({ 4: 'later.exe' })
  })

  it('is empty without pids, without reading the events', () => {
    expect(pidNamesOf([eventOf({ pid: 4, name: 'cmd.exe' })], [])).toEqual({})
  })
})
