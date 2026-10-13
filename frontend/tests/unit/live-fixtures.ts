import type { LiveEvent, LiveProcessNode } from '@/services/live-messages'

export const TS = '2026-10-13T15:39:50.000Z'

export function liveEvent(overrides: Partial<LiveEvent> & { id?: string; lane?: string; pid?: number } = {}): LiveEvent {
  const { id = 'e1', lane = 'file', pid = 9708, ...rest } = overrides
  return {
    '@timestamp': '2026-10-13T15:39:50.412Z',
    event: { id, action: 'file-written', sequence: 1, severity: 0 },
    tartarus: { lane, summary: `benign.exe wrote C:\\Temp\\${id}.txt` },
    process: { pid, name: 'benign.exe' },
    ...rest,
  }
}

export function liveProcess(pid: number, overrides: Partial<LiveProcessNode> = {}): LiveProcessNode {
  return {
    pid,
    ppid: null,
    name: `proc_${pid}.exe`,
    executable: `C:\\Windows\\proc_${pid}.exe`,
    command_line: `proc_${pid}.exe`,
    start: '2026-10-13T15:39:50.000Z',
    end: null,
    ...overrides,
  }
}

export function message(type: string, data: unknown, ts = TS): { type: string; ts: string; data: unknown } {
  return { type, ts, data }
}
