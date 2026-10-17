import type { AnalysisRead, AnalysisStatus, ReportSummary } from '@/api'

export const SHA256 = '9f2c1d0e8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2a1b'

export function analysisFixture(overrides: Partial<AnalysisRead> = {}): AnalysisRead {
  return {
    id: 42,
    sample_sha256: SHA256,
    filename: 'invoice.exe',
    cape_task_id: 7,
    status: 'done',
    phase: 'live',
    options: {},
    score: null,
    max_severity: null,
    detected_families: [],
    event_count: 0,
    disk_bytes: 0,
    queue_position: null,
    error: null,
    submitted_at: '2026-10-13T10:00:00Z',
    started_at: '2026-10-13T10:00:05Z',
    finished_at: '2026-10-13T10:01:17Z',
    deadline_at: null,
    summary: null,
    tags: [],
    guest: null,
    guest_badges: [],
    ...overrides,
  }
}

export function analysisWithStatus(status: AnalysisStatus, overrides: Partial<AnalysisRead> = {}): AnalysisRead {
  return analysisFixture({ status, ...overrides })
}

export const DETECTIONS_SUMMARY: ReportSummary = {
  duration_s: 72,
  process_count: 5,
  signatures: [
    { name: 'creates_exe', severity: 'low', description: 'Creates an executable file' },
    { name: 'injection_rwx', severity: 'high', description: 'Allocates read-write-execute memory' },
    { name: 'dead_connect', severity: 'medium', description: 'Connects to a dead host' },
  ],
  techniques: [
    { id: 'T1055', signatures: ['injection_rwx'] },
    { id: 'T1071', signatures: ['dead_connect'] },
  ],
  network: { dns: 3, hosts: 2, tcp: 4 },
  files_written: 11,
  registry_keys_written: 6,
}

export const NO_DETECTIONS_SUMMARY: ReportSummary = {
  duration_s: 60,
  process_count: 1,
  signatures: [],
  techniques: [],
  network: { dns: 0, hosts: 0, tcp: 0 },
  files_written: 0,
  registry_keys_written: 0,
}
