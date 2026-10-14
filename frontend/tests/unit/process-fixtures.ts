import type { ProcessDetail, ProcessNode, ProcessTree } from '@/api'

export function processNode(pid: number, overrides: Partial<ProcessNode> = {}): ProcessNode {
  return {
    entity_id: `45:${pid}@2026-10-13T15:39:50.393Z`,
    pid,
    ppid: null,
    name: `proc${pid}.exe`,
    executable: `C:\\Users\\Analyst\\AppData\\Local\\Temp\\proc${pid}.exe`,
    command_line: `"C:\\Users\\Analyst\\AppData\\Local\\Temp\\proc${pid}.exe" /run`,
    start: '2026-10-13T15:39:50.393000Z',
    end: '2026-10-13T15:39:51.706000Z',
    integrity: null,
    max_severity: null,
    detection_count: 0,
    injected_into: [],
    network_hosts: [],
    event_counts_by_lane: {},
    tags: [],
    note_count: 0,
    children: [],
    ...overrides,
  }
}

/** benign.exe (high, 5 detections, one host) spawning cmd.exe (medium, 2 detections). */
export function sampleTree(): ProcessTree {
  const child = processNode(2476, {
    ppid: 9708,
    name: 'cmd.exe',
    command_line: 'cmd.exe /c ver',
    max_severity: 'medium',
    detection_count: 2,
    event_counts_by_lane: { api: 225, process: 2 },
  })
  const root = processNode(9708, {
    ppid: 4336,
    name: 'benign.exe',
    max_severity: 'high',
    detection_count: 5,
    network_hosts: ['tartarus-selftest.example'],
    event_counts_by_lane: { api: 248, file: 2, network: 2, registry: 2, process: 1 },
    children: [child],
  })
  return { roots: [root], total: 2 }
}

export function processDetail(node: ProcessNode, overrides: Partial<ProcessDetail> = {}): ProcessDetail {
  const fields: Partial<ProcessNode> = { ...node }
  delete fields.children
  return {
    ...(fields as Omit<ProcessNode, 'children'>),
    modules: [
      { name: 'ntdll.dll', path: null, base_address: '0x7ffd9fd40000', loaded_at: '2026-10-13T15:39:50.940000Z' },
      { name: 'DNSAPI', path: 'C:\\WINDOWS\\SYSTEM32\\DNSAPI', base_address: '0x7ffd9ae50000', loaded_at: '2026-10-13T15:39:51.518000Z' },
    ],
    top_apis: [
      { name: 'NtClose', count: 40 },
      { name: 'NtWriteFile', count: 29 },
    ],
    events: [
      {
        time: '2026-10-13T15:39:56.837000Z',
        action: 'dns-query',
        summary: 'DNS query for tartarus-selftest.example',
        lane: 'network',
        event_id: 'd7997a7c5b75e877b7903eff56450efe3fbcafe1',
      },
    ],
    event_total: 7,
    ...overrides,
  }
}
