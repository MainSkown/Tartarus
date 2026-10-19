import { describe, expect, it } from 'vitest'
import type { IocType } from '@/api'
import {
  describeTarget,
  filterOn,
  flowDestinationFilters,
  hostEntryFilters,
  iocFilters,
  memoryFindingFilters,
  registryChangeFilters,
} from '@/services/events-filters'

describe('filterOn', () => {
  it('is one chip for a value', () => {
    expect(filterOn('url.full', 'http://a.example/x')).toEqual([{ field: 'url.full', value: 'http://a.example/x' }])
  })

  it.each([null, undefined, ''])('is no chip for %j, so a row without the value has no action', (missing) => {
    expect(filterOn('url.full', missing)).toEqual([])
  })

  it('keeps a number as it is', () => {
    expect(filterOn('destination.port', 0)).toEqual([{ field: 'destination.port', value: 0 }])
  })
})

describe('flowDestinationFilters', () => {
  it('is the address and the port', () => {
    expect(flowDestinationFilters('203.0.113.9', 443)).toEqual([
      { field: 'destination.ip', value: '203.0.113.9' },
      { field: 'destination.port', value: 443 },
    ])
  })

  it('is the address alone when there is no port', () => {
    expect(flowDestinationFilters('203.0.113.9', null)).toEqual([{ field: 'destination.ip', value: '203.0.113.9' }])
  })

  it('is nothing without an address, whatever the port', () => {
    expect(flowDestinationFilters(null, 443)).toEqual([])
  })
})

describe('hostEntryFilters', () => {
  it('filters an address on the destination address', () => {
    expect(hostEntryFilters('ip', '10.0.0.5')).toEqual([{ field: 'destination.ip', value: '10.0.0.5' }])
  })

  it('filters a name on the domain alias, which reaches both the DNS name and the destination domain', () => {
    expect(hostEntryFilters('domain', 'a.example')).toEqual([{ field: 'domain', value: 'a.example' }])
  })
})

describe('iocFilters', () => {
  const FILTERED: [IocType, string][] = [
    ['domain', 'domain'],
    ['ip', 'destination.ip'],
    ['url', 'url.full'],
    ['hash', 'file.hash.sha256'],
    ['file', 'file.path'],
    ['registry', 'registry.path'],
  ]

  it.each(FILTERED)('filters a %s indicator on %s', (type, field) => {
    expect(iocFilters(type, 'the-value')).toEqual([{ field, value: 'the-value' }])
  })

  it('has no filter for a mutex, which no event field holds', () => {
    expect(iocFilters('mutex', 'Global\\x')).toEqual([])
  })

  it('has no filter for a type it does not know', () => {
    expect(iocFilters('certificate' as IocType, 'x')).toEqual([])
  })
})

describe('registryChangeFilters', () => {
  it('is the hive and the key of a key change', () => {
    expect(registryChangeFilters({ hive: 'HKCU', key: 'Software\\Tartarus', value_name: null })).toEqual([
      { field: 'registry.hive', value: 'HKCU' },
      { field: 'registry.key', value: 'Software\\Tartarus' },
    ])
  })

  it('adds the value name of a value change', () => {
    expect(registryChangeFilters({ hive: 'HKCU', key: 'Software\\Tartarus', value_name: 'SelfTest' })).toEqual([
      { field: 'registry.hive', value: 'HKCU' },
      { field: 'registry.key', value: 'Software\\Tartarus' },
      { field: 'registry.value', value: 'SelfTest' },
    ])
  })

  it('leaves out a hive the report did not name', () => {
    expect(registryChangeFilters({ hive: null, key: 'Software\\Tartarus', value_name: null })).toEqual([
      { field: 'registry.key', value: 'Software\\Tartarus' },
    ])
  })
})

describe('describeTarget', () => {
  it('lists each chip as field and value', () => {
    expect(
      describeTarget({
        chips: [
          { field: 'destination.ip', value: '1.2.3.4' },
          { field: 'destination.port', value: 443 },
        ],
      }),
    ).toBe('destination.ip: 1.2.3.4 and destination.port: 443')
  })

  it('marks a negated chip', () => {
    expect(describeTarget({ chips: [{ field: 'file.path', value: 'a', negate: true }] })).toBe('NOT file.path: a')
  })

  it('names a process by its pid', () => {
    expect(describeTarget({ pid: 4120 })).toBe('pid: 4120')
  })

  it('quotes a query text', () => {
    expect(describeTarget({ text: 'event.id:(a OR b)' })).toBe('query: event.id:(a OR b)')
  })
})

describe('memoryFindingFilters', () => {
  it('is the plugin, the process and the address of the finding', () => {
    expect(memoryFindingFilters({ plugin: 'windows.malware.malfind', process: { pid: 2184 }, address: '0x1e3eba60000' })).toEqual([
      { field: 'tartarus.memory.plugin', value: 'windows.malware.malfind' },
      { field: 'process.pid', value: 2184 },
      { field: 'tartarus.memory.address', value: '0x1e3eba60000' },
    ])
  })

  it('leaves out the process and the address a finding does not have', () => {
    expect(memoryFindingFilters({ plugin: 'windows.malware.malfind', process: null, address: null })).toEqual([
      { field: 'tartarus.memory.plugin', value: 'windows.malware.malfind' },
    ])
  })
})
