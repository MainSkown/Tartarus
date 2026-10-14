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

/** An alert as the backend's Sigma detection builder writes it (`rule.ruleset: sigma`, ATT&CK ids, the matched condition). */
export function sigmaAlert(overrides: Partial<LiveEvent> & { id?: string; severity?: number } = {}): LiveEvent {
  const { id = 'alert-1', severity = 0, ...rest } = overrides
  return {
    '@timestamp': '2026-10-13T15:39:51.100Z',
    event: { id, action: 'rule-matched', sequence: 7, severity, kind: 'alert' },
    tartarus: { lane: 'registry', summary: 'Tartarus Self-Test Registry Marker Written', detection: { match: 'selection', repeated: 3 } },
    process: { pid: 9708, name: 'benign.exe' },
    rule: { id: '6c17e2ec-0203-4f72-8760-b1b2a72336db', name: 'Tartarus Self-Test Registry Marker Written', ruleset: 'sigma' },
    threat: { technique: { id: ['T1112'] }, tactic: { name: ['Stealth'] } },
    related: { events: ['e1'] },
    ...rest,
  } as LiveEvent
}
