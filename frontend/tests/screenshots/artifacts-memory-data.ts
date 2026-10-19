import type { Page, Route } from '@playwright/test'
import type { Artifact, ArtifactsView, Event, EventDetail, EventPage, MemorySummary, SearchRequest } from '../../src/api/types.gen'
import { errorEnvelope, realView } from './fixtures'
import { ID } from './overview-sources-data'

export { ID }

const MALFIND = 'windows.malware.malfind'
const HOLLOWPROCESSES = 'windows.malware.hollowprocesses'
const GIB = 1024 ** 3

const MZ_HEXDUMP = [
  '4d 5a 45 52 e8 00 00 00 00 5b 48 83 eb 09 53 48',
  '81 c3 f7 0a 01 00 ff d3 c3 00 00 00 00 00 00 00',
  '50 45 00 00 64 86 06 00 00 00 00 00 00 00 00 00',
  'f0 00 22 20 0b 02 0e 1d 00 10 00 00 00 20 00 00',
].join(' ')
const MZ_DISASM = `"
0x1e3eba60000:\tpop\tr10
0x1e3eba60002:\tinc\tebp
0x1e3eba60004:\tpush\trdx
0x1e3eba60005:\tcall\t0x1e3eba6000a
0x1e3eba6000a:\tpop\trbx
0x1e3eba6000b:\tsub\trbx, 9
0x1e3eba6000f:\tpush\trbx
0x1e3eba60010:\tpush\trax
0x1e3eba60013:\tadd\trbx, 0x10af7
0x1e3eba6001a:\tcall\trbx
0x1e3eba6001c:\tret\t
0x1e3eba6001d:\tadd\tbyte ptr [rax], al
0x1e3eba6001f:\tadd\tbyte ptr [rax], al"`

const LONG_PROCESS = `${'a_remarkably_long_process_image_name_'.repeat(5)}.exe`
const LONG_NOTE =
  'The ImageBaseAddress reported from the PEB (0x140000000) does not match the process SectionBaseAddress (0x7ff73f160000); There is no VAD starting at the base address of the process executable (0x7ff73f160000)'

export const MEMORY = {
  kept: { dump_taken: true, findings: 'ok', error: null, dump_bytes: 4 * GIB, dump_deleted: null },
  deleted: { dump_taken: true, findings: 'ok', error: null, dump_bytes: 4 * GIB, dump_deleted: true },
  deleteFailed: { dump_taken: true, findings: 'ok', error: null, dump_bytes: 4 * GIB, dump_deleted: false },
  partial: {
    dump_taken: true,
    findings: 'ok',
    error: 'windows.malware.hollowprocesses failed: volatility3 exited with status 1',
    dump_bytes: 4 * GIB,
    dump_deleted: null,
  },
  unavailable: {
    dump_taken: false,
    findings: 'unavailable',
    error: 'CAPE took no memory dump: the storage has 31.2 GB free, below its floor of 50 GB',
    dump_bytes: null,
    dump_deleted: null,
  },
  failed: {
    dump_taken: true,
    findings: 'failed',
    error: 'volatility3 exited with status 1: windows.malfind.Malfind: unsatisfied requirement plugins.Malfind.kernel.symbol_table_name',
    dump_bytes: 4 * GIB,
    dump_deleted: null,
  },
} satisfies Record<string, MemorySummary>

type Memory = Record<string, string>

function finding(id: string, process: Event['process'], memory: Memory, severity: Event['severity'] = 'high', plugin = MALFIND): Event {
  return {
    id,
    time: '2026-10-12T09:19:41Z',
    sequence: null,
    lane: 'memory',
    kind: 'alert',
    category: ['malware', 'process'],
    action: plugin === MALFIND ? 'injection-detected' : 'hollowing-detected',
    module: 'volatility',
    dataset: plugin === MALFIND ? 'volatility.malfind' : 'volatility.hollowprocesses',
    summary: `${plugin === MALFIND ? 'Executable private memory region' : 'Hollowed process image'}: ${process?.name} (pid ${process?.pid})`,
    severity,
    process,
    api_name: null,
    rule_name: null,
    rule_ruleset: 'volatility',
    destination: null,
    dns_query: null,
    url: null,
    file_path: null,
    registry_path: null,
    fields: { 'tartarus.memory.plugin': plugin, ...memory },
  }
}

function malfindFinding(id: string, process: Event['process'], address: string, note: string | null, severity: Event['severity'] = 'high'): Event {
  return finding(
    id,
    process,
    {
      'tartarus.memory.address': address,
      'tartarus.memory.protection': 'PAGE_EXECUTE_READWRITE',
      ...(note ? { 'tartarus.memory.note': note } : {}),
    },
    severity,
  )
}

function hollowFinding(id: string, process: Event['process'], note: string): Event {
  return finding(id, process, { 'tartarus.memory.address': '0x140000000', 'tartarus.memory.note': note }, 'high', HOLLOWPROCESSES)
}

export const BOTH_PLUGINS: Event[] = [
  malfindFinding('f-1', { pid: 2184, name: 'notepad.exe', entity_id: '46:2184@1' }, '0x1e3eba60000', 'MZ header'),
  malfindFinding('f-2', { pid: 2184, name: 'notepad.exe', entity_id: '46:2184@1' }, '0x1e3ebb20000', null, 'medium'),
  malfindFinding('f-3', { pid: 4312, name: 'explorer.exe', entity_id: '46:4312@1' }, '0x7ff6a1200000', 'Function prologue', 'medium'),
  hollowFinding('f-4', { pid: 6304, name: 'PING.EXE', entity_id: '46:6304@1' }, 'There is no VAD starting at the base address of the process executable (0x7ff73f160000)'),
  hollowFinding('f-5', { pid: 7120, name: 'svchost.exe', entity_id: '46:7120@1' }, 'The ImageBaseAddress reported from the PEB (0x140000000) does not match the process SectionBaseAddress (0x7ff73f160000)'),
]

export const UNKNOWN_PLUGIN: Event[] = [
  ...BOTH_PLUGINS,
  finding('f-6', { pid: 900, name: 'lsass.exe', entity_id: '46:900@1' }, { 'tartarus.memory.address': '0x7ffa00010000', 'tartarus.memory.note': 'Hooked SSDT entry' }, 'low', 'windows.ssdt.SSDT'),
]

export const MANY: Event[] = Array.from({ length: 60 }, (_, index) =>
  malfindFinding(
    `m-${index}`,
    { pid: 1000 + index * 4, name: index % 7 === 0 ? 'powershell.exe' : `worker_${index}.exe`, entity_id: null },
    `0x${(0x1e3eba60000 + index * 0x20000).toString(16)}`,
    index % 3 === 0 ? 'MZ header' : index % 3 === 1 ? 'Function prologue' : null,
    index % 3 === 0 ? 'high' : 'medium',
  ),
)

export const LONG_VALUES: Event[] = [
  malfindFinding('l-1', { pid: 2184, name: LONG_PROCESS, entity_id: null }, `0x${'7ff6a1200000'.repeat(8)}`, 'MZ header'),
  malfindFinding('l-2', { pid: 4312, name: 'explorer.exe', entity_id: null }, '0x7ff6a1200000', `${'A very verbose note that keeps going and going. '.repeat(6)}`, 'medium'),
  hollowFinding('l-3', { pid: 6304, name: LONG_PROCESS, entity_id: null }, LONG_NOTE),
  malfindFinding('l-4', null, '0x1e3eba60000', 'MZ header'),
]

function rawOf(event: Event): Record<string, unknown> {
  const isMalfind = event.fields['tartarus.memory.plugin'] === MALFIND
  const raw: Record<string, unknown> = { PID: event.process?.pid, Process: event.process?.name, Notes: event.fields['tartarus.memory.note'] ?? null }
  return isMalfind ? { ...raw, Hexdump: MZ_HEXDUMP, Disasm: MZ_DISASM, Protection: 'PAGE_EXECUTE_READWRITE', Tag: 'VadS' } : raw
}

function detailOf(event: Event): EventDetail {
  return {
    event,
    source: {
      event: { id: event.id, kind: 'alert', module: 'volatility', dataset: event.dataset },
      process: { pid: event.process?.pid, name: event.process?.name, command_line: `C:\\Windows\\System32\\${event.process?.name ?? 'unknown.exe'} -k netsvcs` },
      tartarus: { lane: 'memory', raw: rawOf(event) },
    },
    related: { references: { items: [], total: 0 }, referenced_by: { items: [], total: 0 } },
    annotations: { tags: [], notes: [] },
  }
}

export interface MemoryMock {
  events?: Event[]
  /** Total the index holds; more than `events` makes the search a truncated one. */
  total?: number
  searchDelayMs?: number
  searchStatus?: number
}

const SEARCH_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/events\/search$/.test(url.pathname)
const DETAIL_URL = (url: URL): boolean => /^\/api\/analyses\/\d+\/events\/[^/]+$/.test(url.pathname) && !url.pathname.endsWith('/search')

export interface MemoryMockState {
  searches: SearchRequest[]
  details: string[]
}

/** Serves the findings search and the event detail of the memory sub-tab. Register it after `mockViews`. */
export async function mockMemoryEvents(page: Page, { events = BOTH_PLUGINS, total, searchDelayMs, searchStatus }: MemoryMock = {}): Promise<MemoryMockState> {
  const state: MemoryMockState = { searches: [], details: [] }
  await page.route(SEARCH_URL, async (route: Route) => {
    state.searches.push(route.request().postDataJSON() as SearchRequest)
    if (searchDelayMs) await new Promise((resolve) => setTimeout(resolve, searchDelayMs))
    if (searchStatus) {
      await route.fulfill({ status: searchStatus, json: errorEnvelope('opensearch_unavailable', 'OpenSearch is not answering') })
      return
    }
    const body: EventPage = { events, total: total ?? events.length, next_cursor: null }
    await route.fulfill({ json: body })
  })
  await page.route(DETAIL_URL, async (route: Route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!)
    state.details.push(id)
    const event = events.find((known) => known.id === id)
    if (!event) {
      await route.fulfill({ status: 404, json: errorEnvelope('not_found', `Event ${id} not found`) })
      return
    }
    await route.fulfill({ json: detailOf(event) })
  })
  return state
}

export const DUMP: Artifact = {
  id: 'memdump0000000000001',
  name: 'memory.dmp',
  size: 4 * GIB,
  sha256: 'b7d1e0f8a93c4d52e61f0a7b8c9d3e2f14a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9',
  md5: null,
  type: 'ELF 64-bit LSB core file, x86-64',
  cape_type: null,
  yara: [],
  source_process: null,
  guest_path: null,
  downloadable: true,
}

export function artifactsWithDump(dump: Artifact | null): ArtifactsView {
  return { ...realView<ArtifactsView>('artifacts'), memory_dump: dump }
}
