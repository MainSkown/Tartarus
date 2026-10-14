import { describe, expect, it } from 'vitest'
import { eventProcess, eventTitle } from '@/services/event-display'
import { eventFixture } from './events-fixtures'

describe('eventProcess', () => {
  it('is the pid and name the process chip shows', () => {
    expect(eventProcess(eventFixture({ id: 'a', process: { pid: 2476, name: 'cmd.exe', entity_id: 'x' } }))).toEqual({ pid: 2476, name: 'cmd.exe' })
  })

  it('keeps a pid with no name', () => {
    expect(eventProcess(eventFixture({ id: 'a', process: { pid: 4, name: null, entity_id: null } }))).toEqual({ pid: 4, name: null })
  })

  it('is nothing for an event with no process, or one with no pid', () => {
    expect(eventProcess(eventFixture({ id: 'a', process: null }))).toBeNull()
    expect(eventProcess(eventFixture({ id: 'a', process: { pid: null, name: 'cmd.exe', entity_id: null } }))).toBeNull()
  })
})

describe('eventTitle', () => {
  it('is the summary', () => {
    expect(eventTitle(eventFixture({ id: 'a', summary: 'cmd.exe wrote a.ps1' }))).toBe('cmd.exe wrote a.ps1')
  })

  it('falls back to the action, then to the id', () => {
    expect(eventTitle(eventFixture({ id: 'a', summary: null, action: 'file-written' }))).toBe('file-written')
    expect(eventTitle(eventFixture({ id: 'a', summary: '', action: null }))).toBe('a')
  })
})
