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

  it('offers the searchable fields the event carries', () => {
    expect(offered).toEqual(expect.arrayContaining(['event.module', 'process.entity_id', 'file.path', 'destination.port', 'destination.domain', 'api.name']))
  })

  it('leaves out the fields the event does not carry, which the table has no values for', () => {
    expect(offered).not.toContain('process.command_line')
  })

  it('leaves out composite aliases and unsearchable fields', () => {
    expect(offered).not.toContain('domain')
    expect(offered).not.toContain('tartarus.raw')
  })

  it('leaves out the fields the default columns already show', () => {
    expect(offered).not.toContain('@timestamp')
    expect(offered).not.toContain('event.action')
    expect(offered).not.toContain('process.name')
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
  })

  it.each([
    ['event.module', 'capemon'],
    ['event.category', 'file, process'],
    ['event.sequence', '0'],
    ['event.id', 'e1'],
    ['api.name', 'NtWriteFile'],
    ['destination.ip', '93.184.216.34'],
    ['destination.port', '443'],
    ['destination.domain', 'example.com'],
    ['dns.question.name', 'example.com'],
    ['file.path', 'C:\\Users\\a.ps1'],
  ])('reads %s from the event', (name, expected) => {
    expect(columnValue(event, name)).toBe(expected)
  })

  it('is empty for a value the event does not have', () => {
    expect(columnValue(event, 'registry.path')).toBe('')
    expect(columnValue(eventFixture({ id: 'x', destination: null }), 'destination.port')).toBe('')
  })

  it('is empty for a field it knows nothing about', () => {
    expect(columnValue(event, 'process.command_line')).toBe('')
  })
})

describe('columnFieldGroups', () => {
  const fields = offeredColumnFields(CATALOG)

  it('groups the fields by what comes before the first dot, in catalog order', () => {
    expect(columnFieldGroups(fields, '').map((group) => group.name)).toEqual(['event', 'process', 'file', 'destination', 'api'])
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
