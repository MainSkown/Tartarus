import type { Event, EventDetail, MemorySummary } from '@/api'
import { eventDetail, eventFixture } from './events-fixtures'

export const MALFIND = 'windows.malware.malfind'
export const HOLLOWPROCESSES = 'windows.malware.hollowprocesses'

export const HEXDUMP = Array.from({ length: 64 }, (_, index) => (index < 2 ? ['4d', '5a'][index]! : (index * 3 % 256).toString(16).padStart(2, '0'))).join(' ')
export const DISASM = '"\n0x1e3eba60000:\tpush\trbp\n0x1e3eba60001:\tmov\trax, qword ptr [rcx]\n0x1e3eba60005:\tret\t"'

export function findingEvent(id: string, overrides: Partial<Event> = {}, memory: Record<string, string> = {}): Event {
  return eventFixture({
    id,
    lane: 'memory',
    kind: 'alert',
    module: 'volatility',
    dataset: 'volatility.malfind',
    summary: `malfind found an executable private region in notepad.exe at ${id}`,
    severity: 'high',
    process: { pid: 2184, name: 'notepad.exe', entity_id: '45:2184@1' },
    fields: {
      'tartarus.memory.plugin': MALFIND,
      'tartarus.memory.address': `0x${id}`,
      'tartarus.memory.protection': 'PAGE_EXECUTE_READWRITE',
      'tartarus.memory.note': 'MZ header',
      ...memory,
    },
    ...overrides,
  })
}

export function hollowEvent(id: string, overrides: Partial<Event> = {}): Event {
  return findingEvent(
    id,
    { dataset: 'volatility.hollowprocesses', process: { pid: 6304, name: 'PING.EXE', entity_id: '45:6304@1' }, ...overrides },
    {
      'tartarus.memory.plugin': HOLLOWPROCESSES,
      'tartarus.memory.address': '0x140000000',
      'tartarus.memory.protection': '',
      'tartarus.memory.note': 'There is no VAD starting at the base address of the process executable (0x7ff73f160000)',
    },
  )
}

export function findingDetail(event: Event, raw: Record<string, unknown> = { Hexdump: HEXDUMP, Disasm: DISASM, PID: 2184 }): EventDetail {
  return eventDetail(event, {
    source: { event: { id: event.id }, process: { pid: 2184, command_line: 'C:\\Windows\\System32\\notepad.exe C:\\Users\\Analyst\\a.txt' }, tartarus: { raw } },
  })
}

export function memorySummary(overrides: Partial<MemorySummary> = {}): MemorySummary {
  return { dump_taken: true, findings: 'ok', error: null, dump_bytes: 4 * 1024 ** 3, dump_deleted: true, ...overrides }
}
