import { describe, expect, it } from 'vitest'
import type { MemorySummary } from '@/api'
import { dumpFileStatus, dumpStatusText, findingsStatusText } from '@/services/memory-status'

function memory(overrides: Partial<MemorySummary> = {}): MemorySummary {
  return { dump_taken: true, findings: 'ok', error: null, dump_bytes: 2_147_483_648, dump_deleted: null, ...overrides }
}

describe('dumpStatusText', () => {
  it('says the dump was taken, with its size when known', () => {
    expect(dumpStatusText(memory())).toBe('taken, 2 GB')
    expect(dumpStatusText(memory({ dump_bytes: null }))).toBe('taken')
  })

  it('says it was not taken', () => {
    expect(dumpStatusText(memory({ dump_taken: false }))).toBe('not taken')
  })
})

describe('findingsStatusText', () => {
  it('says the findings were read, with the count of memory events when it is known', () => {
    expect(findingsStatusText(memory())).toBe('findings read')
    expect(findingsStatusText(memory(), 1)).toBe('findings read, 1 memory event')
    expect(findingsStatusText(memory(), 37)).toBe('findings read, 37 memory events')
  })

  it('says there were none to read without a dump, and that reading them failed', () => {
    expect(findingsStatusText(memory({ findings: 'unavailable' }), 5)).toBe('no findings: there was no dump to read')
    expect(findingsStatusText(memory({ findings: 'failed' }))).toBe('findings failed')
  })
})

describe('dumpFileStatus', () => {
  it('is nothing when no dump was taken', () => {
    expect(dumpFileStatus(memory({ dump_taken: false }))).toBeNull()
  })

  it('says whether the file was kept, deleted after the findings, or could not be deleted (a warning)', () => {
    expect(dumpFileStatus(memory({ dump_deleted: null }))).toEqual({ text: 'kept', warn: false })
    expect(dumpFileStatus(memory({ dump_deleted: true }))).toEqual({ text: 'deleted after the findings', warn: false })
    expect(dumpFileStatus(memory({ dump_deleted: false }))).toEqual({ text: 'could not be deleted', warn: true })
  })
})
