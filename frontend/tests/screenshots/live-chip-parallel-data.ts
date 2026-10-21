import type { AnalysisRead, Guest, QueueSnapshot, QueuedAnalysis, RunningAnalysis, SettingsBody } from '../../src/api/types.gen'
import { makeAnalysis, makeCleanAnalysis } from './fixtures'

const LONG_FILENAME = `quarterly_financial_report_final_FINAL_v2_signed_by_the_ceo_and_cfo_${'x'.repeat(40)}.pdf.exe`

export const SETTINGS: SettingsBody = {
  default_route: 'inetsim',
  default_timeout: 180,
  default_interactive: false,
  disk_warn_gb: 80,
  disk_block_gb: 30,
}

export const GUESTS: Guest[] = [
  { name: 'lab1', state: 'ready', profile: 'windows', badges: ['DEFENDER OFF'] },
  { name: 'lab2', state: 'ready', profile: 'windows', badges: ['DEFENDER ON'] },
  { name: 'lab3', state: 'ready', profile: 'windows', badges: [] },
  { name: 'lab4', state: 'building', profile: 'windows', badges: [] },
]

function startedAgo(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString()
}

export function runningAnalysis(id: number, filename: string, guest: string | null, secondsAgo: number): AnalysisRead {
  return makeAnalysis({
    id,
    filename,
    guest,
    status: 'running',
    started_at: startedAgo(secondsAgo),
    submitted_at: startedAgo(secondsAgo + 5),
  })
}

export function queuedAnalysis(id: number, filename: string, guest: string | null, position: number): AnalysisRead {
  return makeAnalysis({ id, filename, guest, status: 'queued', queue_position: position })
}

function asRunning(analysis: AnalysisRead): RunningAnalysis {
  return {
    id: analysis.id,
    filename: analysis.filename,
    guest: analysis.guest,
    status: analysis.status,
    started_at: analysis.started_at,
    elapsed_s: null,
  }
}

function asQueued(analysis: AnalysisRead): QueuedAnalysis {
  return { id: analysis.id, filename: analysis.filename, guest: analysis.guest, position: analysis.queue_position ?? 1 }
}

/** The `/api/system/queue` snapshot for the given running and queued analyses, as the backend builds it. */
export function queueOf(running: AnalysisRead[], queued: AnalysisRead[]): QueueSnapshot {
  return { running: running.map(asRunning), queued_count: queued.length, queued: queued.map(asQueued) }
}

export const ONE_RUNNING = [runningAnalysis(42, 'invoice.exe', 'lab1', 72)]

export const THREE_RUNNING = [
  runningAnalysis(41, 'dropper.dll', 'lab1', 310),
  runningAnalysis(42, 'invoice.exe', 'lab2', 72),
  runningAnalysis(43, 'macro.doc', null, 3725),
]

export const TWO_QUEUED = [queuedAnalysis(44, 'loader.ps1', 'lab1', 1), queuedAnalysis(45, 'stage2.msi', 'lab2', 1)]

export const LONG_NAME_RUNNING = [
  runningAnalysis(41, LONG_FILENAME, 'malware-lab-windows-11-enterprise-defender-off-no-decoys', 310),
  runningAnalysis(42, `${'invoice_'.repeat(8)}scan.exe`, 'lab2', 72),
  runningAnalysis(43, 'short.exe', 'lab3', 9),
]

export const LONG_NAME_QUEUED = [queuedAnalysis(44, LONG_FILENAME, 'malware-lab-windows-11-enterprise-defender-off-no-decoys', 1)]

export const MANY_QUEUED = Array.from({ length: 11 }, (_, index) =>
  queuedAnalysis(50 + index, `batch_sample_${index + 1}.exe`, index % 2 === 0 ? 'lab1' : 'lab2', Math.floor(index / 2) + 1),
)

/** Finished analyses behind the Dashboard list, so a populated table is the backdrop for the chip. */
export const FINISHED_BACKDROP: AnalysisRead[] = [
  makeCleanAnalysis({ id: 30, filename: 'notepad_portable.exe', guest: 'lab3' }),
  makeCleanAnalysis({ id: 29, filename: 'setup_helper.exe', guest: 'lab1' }),
]

export const NONE_RUNNING_BACKDROP: AnalysisRead[] = FINISHED_BACKDROP

export function dashboardItems(...groups: AnalysisRead[][]): AnalysisRead[] {
  return groups.flat()
}
