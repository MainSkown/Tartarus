import { describe, expect, it } from 'vitest'
import type { FieldRead } from '@/api'
import { columnFieldGroups, columnValue, offeredColumnFields } from '@/services/event-columns'
import { eventFixture } from './events-fixtures'

function field(name: string, overrides: Partial<FieldRead> = {}): FieldRead {
  return { name, type: 'keyword', aliases: [], description: `about ${name}`, example: '', lane: null, members: [], searchable: true, ...overrides }
}

const CATALOG: FieldRead[] = [
  field('@timestamp', { type: 'date' }),
  field('event.action'),
  field('event.module'),
  field('process.name'),
  field('process.entity_id'),
  field('process.command_line', { type: 'keyword_with_text' }),
  field('file.path', { type: 'keyword_with_text' }),
  field('destination.port', { type: 'long' }),
  field('destination.domain'),
  field('api.name'),
  field('domain', { members: ['dns.question.name', 'destination.domain'] }),
  field('tartarus.raw', { type: 'object_disabled', searchable: false }),
]

describe('offeredColumnFields', () => {
  const offered = offeredColumnFields(CATALOG).map((entry) => entry.name)

  it('offers every searchable field, including those the typed event does not carry', () => {
    expect(offered).toEqual(
      expect.arrayContaining(['process.command_line', 'event.module', 'file.path', 'destination.port', 'api.name', 'process.name', 'event.action']),
    )
  })

  it('leaves out composite aliases and unsearchable fields', () => {
    expect(offered).not.toContain('domain')
    expect(offered).not.toContain('tartarus.raw')
  })
})

describe('columnValue', () => {
  const event = eventFixture({
    id: 'e1',
    module: 'capemon',
    category: ['file', 'process'],
    sequence: 0,
    api_name: 'NtWriteFile',
    destination: { ip: '93.184.216.34', port: 443, domain: 'example.com' },
    dns_query: 'example.com',
    file_path: 'C:\\Users\\a.ps1',
    registry_path: null,
    fields: {
      'process.command_line': 'cmd.exe /c whoami',
      'event.sequence': 7,
      'api.status': true,
      'event.category': ['a', 'b'],
      'api.arguments': { FileName: 'a.ps1', Handle: 12, Nested: { x: 1 } },
      'file.size': null,
    },
  })

  it('shows a scalar the search returned as text, numbers and booleans too', () => {
    expect(columnValue(event, 'process.command_line')).toBe('cmd.exe /c whoami')
    expect(columnValue(event, 'api.status')).toBe('true')
  })

  it('prefers the returned value over the typed one', () => {
    expect(columnValue(event, 'event.sequence')).toBe('7')
    expect(columnValue(event, 'event.category')).toBe('a, b')
  })

  it('joins an array with a comma and a space', () => {
    expect(columnValue(eventFixture({ id: 'x', fields: { 'dns.answers.data': ['1.1.1.1', '2.2.2.2'] } }), 'dns.answers.data')).toBe('1.1.1.1, 2.2.2.2')
  })

  it('writes an object as compact key=value pairs', () => {
    expect(columnValue(event, 'api.arguments')).toBe('FileName=a.ps1, Handle=12, Nested={"x":1}')
  })

  it.each([
    ['event.module', 'capemon'],
    ['event.id', 'e1'],
    ['api.name', 'NtWriteFile'],
    ['destination.ip', '93.184.216.34'],
    ['destination.port', '443'],
    ['destination.domain', 'example.com'],
    ['dns.question.name', 'example.com'],
    ['file.path', 'C:\\Users\\a.ps1'],
    ['process.name', 'cmd.exe'],
    ['process.pid', '2476'],
    ['tartarus.lane', 'process'],
    ['event.action', 'process-created'],
    ['@timestamp', '2026-10-13T15:39:33.863Z'],
  ])('falls back to the typed event for %s', (name, expected) => {
    expect(columnValue(event, name)).toBe(expected)
  })

  it('is empty for a value the event does not have, a null, or a field it knows nothing about', () => {
    expect(columnValue(event, 'registry.path')).toBe('')
    expect(columnValue(event, 'file.size')).toBe('')
    expect(columnValue(event, 'http.request.method')).toBe('')
    expect(columnValue(eventFixture({ id: 'x', destination: null }), 'destination.port')).toBe('')
  })
})

describe('columnFieldGroups', () => {
  const fields = offeredColumnFields(CATALOG)

  it('groups the fields by what comes before the first dot, in catalog order, a field with no dot going under "common"', () => {
    expect(columnFieldGroups(fields, '').map((group) => group.name)).toEqual(['common', 'event', 'process', 'file', 'destination', 'api'])
  })

  it('narrows to the fields whose name or description holds the search, in any case', () => {
    const groups = columnFieldGroups(fields, 'DEST')
    expect(groups.map((group) => group.name)).toEqual(['destination'])
    expect(groups[0]!.fields.map((entry) => entry.name)).toEqual(['destination.port', 'destination.domain'])
    expect(columnFieldGroups(fields, 'about api').map((group) => group.name)).toEqual(['api'])
  })

  it('finds nothing for a search nothing matches', () => {
    expect(columnFieldGroups(fields, 'zzz')).toEqual([])
  })
})
