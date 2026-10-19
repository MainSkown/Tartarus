import type { AnalysisRead, DefenderThreat, DefenderVerdict, MemorySummary } from '../../src/api/types.gen'
import { makeDetectedAnalysis } from './fixtures'

export const ID = 46
const LANE_COUNTS = { api: 472, network: 217, process: 15, file: 4, registry: 2, memory: 37 }
const SAMPLE_PATH = 'C:\\Users\\Alice\\AppData\\Local\\Temp\\321\\eicar.com'
const LONG_PATH = `C:\\Users\\Alice\\AppData\\Local\\Temp\\${'DeeplyNestedFolderName\\'.repeat(6)}a-very-long-dropped-payload-name-that-keeps-going-and-going.dll`
const LONG_THREAT = 'Trojan:Win32/Wacatac.B!ml.A-very-long-heuristic-detection-name-with-no-spaces-at-all-to-test-wrapping'

export function threat(overrides: Partial<DefenderThreat> = {}): DefenderThreat {
  return {
    detection_id: '{A}',
    threat_id: 2147519003,
    name: 'Virus:DOS/EICAR_Test_File',
    severity: 4,
    category_id: 42,
    scope: 'sample',
    path: SAMPLE_PATH,
    process: 'C:\\Python311\\pythonw.exe',
    user: null,
    detected_at: '2026-10-12T09:14:31Z',
    action: 'Quarantine',
    outcome: 'removed',
    removed_at: '2026-10-12T09:14:44Z',
    ...overrides,
  }
}

function verdict(overrides: Partial<DefenderVerdict> = {}): DefenderVerdict {
  return { status: 'removed', sample_removed: true, blocked_before_run: false, threats: [threat()], ...overrides }
}

export const DEFENDER = {
  removedSample: verdict(),
  removedDropped: verdict({
    sample_removed: false,
    threats: [threat({ scope: 'dropped', name: 'Trojan:Win32/Dropper.A', severity: 3, path: 'C:\\Users\\Public\\tt-dropped-eicar.txt' })],
  }),
  blocked: verdict({ blocked_before_run: true }),
  detected: verdict({
    status: 'detected',
    sample_removed: false,
    threats: [threat({ outcome: 'pending', action: 'Not applicable', removed_at: null, severity: 3 })],
  }),
  failed: verdict({
    status: 'failed',
    sample_removed: false,
    threats: [threat({ outcome: 'failed', action: 'Remove', removed_at: null })],
  }),
  clean: verdict({ status: 'clean', sample_removed: false, threats: [] }),
  noExport: verdict({ status: 'no_export', sample_removed: false, threats: [] }),
  longValues: verdict({
    threats: [threat({ name: LONG_THREAT, scope: 'dropped', path: LONG_PATH })],
  }),
  many: verdict({
    threats: Array.from({ length: 10 }, (_, index) =>
      threat({
        detection_id: `{${index}}`,
        name: `Trojan:Win32/Stage${index + 1}.A`,
        scope: index === 0 ? 'sample' : 'dropped',
        severity: (index % 4) + 1,
        path: `C:\\Users\\Alice\\AppData\\Roaming\\Stage${index + 1}\\payload${index + 1}.dll`,
        outcome: index === 3 ? 'failed' : index === 6 ? 'pending' : 'removed',
        removed_at: index === 3 || index === 6 ? null : '2026-10-12T09:14:44Z',
      }),
    ),
  }),
}

export const MEMORY: Record<'ok' | 'unavailable' | 'failed' | 'kept', MemorySummary> = {
  ok: { dump_taken: true, findings: 'ok', error: null, dump_bytes: 4 * 1024 ** 3, dump_deleted: true },
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
    dump_bytes: 4 * 1024 ** 3,
    dump_deleted: false,
  },
  kept: { dump_taken: true, findings: 'ok', error: null, dump_bytes: 2_147_483_648, dump_deleted: null },
}

export const HIDDEN_EVENTS = { 'windows-background': 4210, 'cape-tooling': 112, 'monitor-artefact': 9, 'sysmon-service': 3, 'unmapped-event': 5 }

interface SourceSummary {
  defender?: DefenderVerdict | null
  hidden_events?: Record<string, number>
  memory?: MemorySummary | null
  badges?: string[]
  processCount?: number
}

export function analysisWithSources({ defender, hidden_events, memory, badges = ['DEFENDER ON', 'SYSMON'], processCount }: SourceSummary): AnalysisRead {
  const base = makeDetectedAnalysis({ id: ID, guest: 'lab5', guest_badges: badges })
  return {
    ...base,
    summary: {
      ...base.summary,
      lane_counts: LANE_COUNTS,
      ...(processCount === undefined ? {} : { process_count: processCount }),
      ...(defender === undefined ? {} : { defender }),
      ...(hidden_events === undefined ? {} : { hidden_events }),
      ...(memory === undefined ? {} : { memory }),
    },
  }
}

export function emptyRunAnalysis(): AnalysisRead {
  const base = analysisWithSources({ defender: DEFENDER.blocked, hidden_events: { 'windows-background': 53 }, processCount: 0 })
  return {
    ...base,
    score: 0,
    max_severity: null,
    detected_families: [],
    summary: { ...base.summary, duration_s: 10, files_written: 0, registry_keys_written: 0, signatures: [], techniques: [], network: { dns: 0, hosts: 0, tcp: 51 }, lane_counts: { network: 53 } },
  }
}

export function oldSummaryAnalysis(): AnalysisRead {
  const base = makeDetectedAnalysis({ id: ID, guest: 'lab5', guest_badges: ['DEFENDER ON'] })
  return { ...base, summary: { ...base.summary, lane_counts: LANE_COUNTS } }
}
