import type { AnalysisRead, Artifact, ArtifactsView, IocsView, RegistryView } from '@/api'
import { analysisFixture } from './analysis-fixtures'

export const ANALYSIS: AnalysisRead = analysisFixture({ id: 45 })

export const DROPPER_HASH = '19e19f9e997696d63c3a2ef193633c001b032b3880fd4b487dfea606aa77c196'

export function artifactFixture(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: '11718311428567399a1c',
    name: 'tartarus-benign.txt',
    size: 33,
    sha256: DROPPER_HASH,
    md5: 'fba3232a4e0d640527227f4465942beb',
    type: 'ASCII text, with CRLF line terminators',
    cape_type: null,
    yara: [],
    source_process: { pid: 9708, name: 'benign.exe' },
    guest_path: 'C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt',
    downloadable: true,
    ...overrides,
  }
}

export function artifactsViewFixture(overrides: Partial<ArtifactsView> = {}): ArtifactsView {
  return {
    dropped: [artifactFixture()],
    payloads: [],
    procdumps: [
      artifactFixture({
        id: 'a70d91df180724fba958',
        name: 'cmd.exe',
        size: 435712,
        sha256: 'c9e9eee4448a15c1b9d290488c19a49bb4cb824aca01778c26199f8d5a98b771',
        type: 'PE32+ executable (console) x86-64, for MS Windows',
        guest_path: 'C:\\Windows\\System32\\cmd.exe',
        source_process: { pid: 2476, name: 'cmd.exe' },
      }),
    ],
    memory_dump: null,
    pcap: null,
    screenshots: [],
    configs: [],
    ...overrides,
  }
}

export const EMPTY_ARTIFACTS_VIEW: ArtifactsView = artifactsViewFixture({ dropped: [], procdumps: [] })

export function registryViewFixture(): RegistryView {
  return {
    keys: [
      {
        key: 'Software\\Tartarus',
        hive: 'HKCU',
        changes: [
          {
            event_id: 'e1',
            time: '2026-10-13T15:39:51.503000Z',
            action: 'reg-key-created',
            value_name: null,
            data_type: null,
            data: [],
            process: { pid: 9708, name: 'benign.exe' },
          },
          {
            event_id: 'e2',
            time: '2026-10-13T15:39:52.000000Z',
            action: 'reg-value-set',
            value_name: 'SelfTest',
            data_type: 'REG_SZ',
            data: ['benign'],
            process: { pid: 9708, name: 'benign.exe' },
          },
        ],
      },
      {
        key: 'Software\\Microsoft\\Windows\\CurrentVersion\\Run',
        hive: 'HKCU',
        changes: [
          {
            event_id: 'e3',
            time: '2026-10-13T15:40:00.000000Z',
            action: 'reg-value-set',
            value_name: 'Updater',
            data_type: 'REG_SZ',
            data: ['C:\\Users\\Analyst\\updater.exe'],
            process: null,
          },
        ],
      },
    ],
    total: 3,
  }
}

export function iocsViewFixture(overrides: Partial<IocsView> = {}): IocsView {
  return {
    iocs: [
      { type: 'hash', value: DROPPER_HASH, count: 1, context: 'Dropped file tartarus-benign.txt', source_event_ids: [], process: { pid: 9708, name: 'benign.exe' }, first_seen: null },
      { type: 'domain', value: 'tartarus-selftest.example', count: 2, context: 'benign.exe resolved tartarus-selftest.example', source_event_ids: ['a', 'b'], process: { pid: 9708, name: 'benign.exe' }, first_seen: null },
      { type: 'domain', value: 'outlook.office.com', count: 1, context: 'DNS query for outlook.office.com', source_event_ids: ['c'], process: null, first_seen: null },
      { type: 'url', value: 'http://www.msftconnecttest.com/connecttest.txt', count: 1, context: 'GET http://www.msftconnecttest.com/connecttest.txt', source_event_ids: ['d'], process: null, first_seen: null },
    ],
    truncated_types: [],
    ...overrides,
  }
}
