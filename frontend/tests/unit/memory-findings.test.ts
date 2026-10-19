import { describe, expect, it } from 'vitest'
import {
  MEMORY_FINDINGS_SIZE,
  findingFromEvent,
  groupFindings,
  memoryFindingsRequest,
  pluginHelp,
  pluginName,
  processCommandLine,
  regionPreview,
  type MemoryFinding,
} from '@/services/memory-findings'
import { eventFixture } from './events-fixtures'

const MALFIND = 'windows.malware.malfind'
const HOLLOW = 'windows.malware.hollowprocesses'

function malfindEvent(id = 'f1', overrides: Parameters<typeof eventFixture>[0] extends infer T ? Partial<T> : never = {}) {
  return eventFixture({
    id,
    lane: 'memory',
    kind: 'alert',
    module: 'volatility',
    dataset: 'volatility.malfind',
    severity: 'high',
    process: { pid: 2184, name: 'notepad.exe', entity_id: '45:2184' },
    fields: {
      'tartarus.memory.plugin': MALFIND,
      'tartarus.memory.address': '0x1e3eba60000',
      'tartarus.memory.protection': 'PAGE_EXECUTE_READWRITE',
      'tartarus.memory.note': 'MZ header',
    },
    ...overrides,
  })
}

function finding(plugin: string, id: string): MemoryFinding {
  return { id, plugin, address: null, protection: null, note: null, severity: 'medium', process: null }
}

describe('memoryFindingsRequest', () => {
  it('asks for the Volatility detections of the memory lane, with the memory fields as columns', () => {
    expect(memoryFindingsRequest()).toEqual({
      filters: [
        { field: 'event.module', value: 'volatility' },
        { field: 'event.kind', value: 'alert' },
      ],
      lanes: ['memory'],
      size: MEMORY_FINDINGS_SIZE,
      columns: ['tartarus.memory.plugin', 'tartarus.memory.address', 'tartarus.memory.protection', 'tartarus.memory.note'],
    })
  })
})

describe('findingFromEvent', () => {
  it('reads the plugin, address, protection and note from the returned columns', () => {
    expect(findingFromEvent(malfindEvent())).toEqual({
      id: 'f1',
      plugin: MALFIND,
      address: '0x1e3eba60000',
      protection: 'PAGE_EXECUTE_READWRITE',
      note: 'MZ header',
      severity: 'high',
      process: { pid: 2184, name: 'notepad.exe' },
    })
  })

  it('leaves out what the plugin did not give, as hollowprocesses gives no protection', () => {
    const event = malfindEvent('f2', { fields: { 'tartarus.memory.plugin': HOLLOW, 'tartarus.memory.note': 'no VAD at the base' } })
    expect(findingFromEvent(event)).toMatchObject({ plugin: HOLLOW, address: null, protection: null, note: 'no VAD at the base' })
  })

  it('falls back to the dataset for the plugin when the column is absent', () => {
    expect(findingFromEvent(malfindEvent('f3', { fields: {} })).plugin).toBe('malfind')
  })

  it('has no process for an event that names none by pid', () => {
    expect(findingFromEvent(malfindEvent('f4', { process: null })).process).toBeNull()
  })

  it('is info when the event carries no severity', () => {
    expect(findingFromEvent(malfindEvent('f5', { severity: null })).severity).toBe('info')
  })
})

describe('pluginName', () => {
  it('is the last segment of the full plugin name', () => {
    expect(pluginName(MALFIND)).toBe('malfind')
    expect(pluginName('windows.pslist.PsList')).toBe('PsList')
  })

  it('is the name itself when it has no dots', () => {
    expect(pluginName('custom')).toBe('custom')
  })
})

describe('groupFindings', () => {
  it('groups by plugin with malfind first, then hollowprocesses, then unknown plugins as they were received', () => {
    const groups = groupFindings([
      finding('windows.vadinfo.VadInfo', 'a'),
      finding(HOLLOW, 'b'),
      finding(MALFIND, 'c'),
      finding('windows.ssdt.SSDT', 'd'),
      finding(MALFIND, 'e'),
    ])
    expect(groups.map((group) => [group.name, group.findings.map((item) => item.id)])).toEqual([
      ['malfind', ['c', 'e']],
      ['hollowprocesses', ['b']],
      ['VadInfo', ['a']],
      ['SSDT', ['d']],
    ])
  })

  it('has no group for a plugin without findings', () => {
    expect(groupFindings([finding(MALFIND, 'a')]).map((group) => group.name)).toEqual(['malfind'])
  })

  it('is empty without findings', () => {
    expect(groupFindings([])).toEqual([])
  })
})

describe('regionPreview', () => {
  const source = (raw: unknown) => ({ tartarus: { raw } })

  it('reads the hex dump and the disassembly of the Volatility row kept as tartarus.raw', () => {
    expect(regionPreview(source({ Hexdump: '4d 5a 90', Disasm: '"\n0x1:\tpush\trbp"' }))).toEqual({ hexdump: '4d 5a 90', disasm: '"\n0x1:\tpush\trbp"' })
  })

  it('has neither for a plugin that does not read the region, such as hollowprocesses', () => {
    expect(regionPreview(source({ PID: 6304, Notes: 'no VAD' }))).toEqual({ hexdump: null, disasm: null })
  })

  it.each([undefined, null, 'text', 5, [1]])('has neither when tartarus.raw is %j', (raw) => {
    expect(regionPreview(source(raw))).toEqual({ hexdump: null, disasm: null })
  })

  it('has neither for a document without a tartarus section', () => {
    expect(regionPreview({})).toEqual({ hexdump: null, disasm: null })
  })

  it('ignores a hex dump that is not text', () => {
    expect(regionPreview(source({ Hexdump: 12 }))).toEqual({ hexdump: null, disasm: null })
  })
})

describe('processCommandLine', () => {
  it('is the command line of the process the finding is in', () => {
    expect(processCommandLine({ process: { command_line: 'C:\\Windows\\notepad.exe a.txt' } })).toBe('C:\\Windows\\notepad.exe a.txt')
  })

  it.each([{}, { process: {} }, { process: { command_line: 3 } }, { process: 'x' }])('is nothing for %j', (source) => {
    expect(processCommandLine(source)).toBeNull()
  })
})

describe('pluginHelp', () => {
  it('says in a few words what a known plugin finds, and nothing for an unknown one', () => {
    expect(pluginHelp('malfind')).toContain('executable private memory regions')
    expect(pluginHelp('hollowprocesses')).toContain('image was replaced')
    expect(pluginHelp('VadInfo')).toBeUndefined()
  })
})
