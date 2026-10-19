import { describe, expect, it } from 'vitest'
import { isMemoryDumpRefusal, memoryDumpDiskGb } from '@/services/memory-dump'

describe('memoryDumpDiskGb', () => {
  it('is the guest RAM in GB plus 0.3 GB of findings, for a 4096 MB guest', () => {
    expect(memoryDumpDiskGb(4096)).toBe(4.3)
  })

  it('scales with the guest RAM', () => {
    expect(memoryDumpDiskGb(16384)).toBe(16.3)
  })

  it('rounds the RAM up to one decimal before adding the findings', () => {
    expect(memoryDumpDiskGb(4100)).toBe(4.4)
  })
})

describe('isMemoryDumpRefusal', () => {
  it('recognises the backend refusal for a dump that needs more free disk', () => {
    expect(isMemoryDumpRefusal('A memory dump needs 20.3 GB free on the CAPE volume; 12.0 GB are free.')).toBe(true)
  })

  it('leaves other conflicts to the banner', () => {
    expect(isMemoryDumpRefusal('A guest is being built')).toBe(false)
    expect(isMemoryDumpRefusal('Refused: a memory dump needs free disk')).toBe(false)
  })
})
