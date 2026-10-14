import { describe, expect, it } from 'vitest'
import { flattenSource } from '@/services/event-source'

describe('flattenSource', () => {
  it('turns nested objects into dotted field names, in document order', () => {
    expect(
      flattenSource({
        '@timestamp': '2026-10-13T15:39:33.863Z',
        event: { action: 'file-written', kind: 'event' },
        process: { pid: 2476, name: 'cmd.exe', parent: { pid: 1020 } },
      }),
    ).toEqual([
      { name: '@timestamp', value: '2026-10-13T15:39:33.863Z' },
      { name: 'event.action', value: 'file-written' },
      { name: 'event.kind', value: 'event' },
      { name: 'process.pid', value: '2476' },
      { name: 'process.name', value: 'cmd.exe' },
      { name: 'process.parent.pid', value: '1020' },
    ])
  })

  it('gives each value of a list its own row under the same name', () => {
    expect(flattenSource({ event: { category: ['file', 'process'] } })).toEqual([
      { name: 'event.category', value: 'file' },
      { name: 'event.category', value: 'process' },
    ])
  })

  it('writes booleans and numbers as text and leaves out null and empty values', () => {
    expect(flattenSource({ api: { status: false, repeated: 0, note: null, tags: [] } })).toEqual([
      { name: 'api.status', value: 'false' },
      { name: 'api.repeated', value: '0' },
    ])
  })

  it('keeps an empty string, which is a value', () => {
    expect(flattenSource({ registry: { value: '' } })).toEqual([{ name: 'registry.value', value: '' }])
  })

  it('leaves out the original record, which the raw JSON shows whole', () => {
    expect(flattenSource({ tartarus: { lane: 'file', raw: { a: 1 } } })).toEqual([{ name: 'tartarus.lane', value: 'file' }])
  })

  it('flattens the objects inside a list', () => {
    expect(flattenSource({ dns: { answers: [{ data: '1.2.3.4' }, { data: '5.6.7.8' }] } })).toEqual([
      { name: 'dns.answers.data', value: '1.2.3.4' },
      { name: 'dns.answers.data', value: '5.6.7.8' },
    ])
  })
})
