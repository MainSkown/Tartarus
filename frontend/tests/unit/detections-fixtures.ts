import type { ArtifactsView, AttackMatrix, Detection, DetectionsView, RelatedEvent } from '@/api'

const BENIGN = { pid: 9708, name: 'benign.exe' }

const SELFTEST_EVENT: RelatedEvent = {
  id: 'event-selftest',
  time: '2026-10-13T15:39:51.100000Z',
  lane: 'registry',
  action: 'registry-value-set',
  summary: 'benign.exe set HKCU\\Software\\Tartarus\\SelfTest',
  process: BENIGN,
}

export function relatedEvent(index: number): RelatedEvent {
  return {
    id: `event-${index}`,
    time: `2026-10-13T15:39:5${index % 10}.531000Z`,
    lane: 'api',
    action: 'api-call',
    summary: `benign.exe called DllLoadNotification #${index}`,
    process: BENIGN,
  }
}

export function detectionFixture(overrides: Partial<Detection> = {}): Detection {
  return {
    id: 'det-1',
    name: 'recon_systeminfo',
    description: 'Collects information on the system (ipconfig, netstat, systeminfo)',
    severity: 'high',
    ruleset: 'cape',
    techniques: [],
    match: null,
    references: [],
    time: '2026-10-13T15:39:50.753000Z',
    process: BENIGN,
    related_events: [],
    related_event_total: 0,
    ...overrides,
  }
}

export const SIGMA_ID = 'det-sigma'
export const SIGMA_SELFTEST_ID = 'det-sigma-selftest'
export const CAPE_DLL_ID = 'det-dll'
export const CAPE_RECON_ID = 'det-recon'
export const SURICATA_ID = 'det-suricata'

export const DETECTIONS_VIEW: DetectionsView = {
  total: 5,
  groups: [
    {
      ruleset: 'cape',
      detections: [
        detectionFixture({
          id: CAPE_DLL_ID,
          name: 'dllload_suspicious_directory',
          description: 'A DLL was loaded from a suspicious directory',
          severity: 'medium',
          techniques: ['T1574'],
          match: 'suspicious_dll_load: Process benign.exe loaded a DLL from a suspicious directory',
          related_events: Array.from({ length: 10 }, (_, index) => relatedEvent(index)),
          related_event_total: 52,
        }),
        detectionFixture({
          id: CAPE_RECON_ID,
          related_events: [relatedEvent(100), relatedEvent(101)],
          related_event_total: 2,
        }),
      ],
    },
    {
      ruleset: 'suricata',
      detections: [
        detectionFixture({
          id: SURICATA_ID,
          name: 'ET MALWARE Possible beacon',
          description: null,
          ruleset: 'suricata',
          techniques: ['T1071'],
          references: ['https://example.com/sid/2012345', 'javascript:alert(1)'],
          process: null,
        }),
      ],
    },
    {
      ruleset: 'sigma',
      detections: [
        detectionFixture({
          id: SIGMA_ID,
          name: 'proc_injection_remote_thread',
          description: 'Remote thread created in another process',
          severity: 'critical',
          ruleset: 'sigma',
          techniques: ['T1055', 'T1055.003'],
          match: 'selection and not filter_main_csrss',
          references: ['https://attack.mitre.org/techniques/T1055/'],
        }),
        // The shape the backend's Sigma detection builder writes for the shipped self-test rule:
        // level informational, the matched condition (not the selection), one triggering event.
        detectionFixture({
          id: SIGMA_SELFTEST_ID,
          name: 'Tartarus Self-Test Registry Marker Written',
          description:
            'The sample the Tartarus end-to-end run detonates writes the value SelfTest under HKCU\\Software\\Tartarus on every run.',
          severity: 'info',
          ruleset: 'sigma',
          techniques: ['T1112'],
          match: 'selection',
          time: '2026-10-13T15:39:51.100000Z',
          related_events: [SELFTEST_EVENT],
          related_event_total: 1,
        }),
      ],
    },
  ],
}

export const EMPTY_DETECTIONS_VIEW: DetectionsView = { groups: [], total: 0 }

export const ATTACK_MATRIX: AttackMatrix = {
  attack_version: '19.2',
  tactics: [
    {
      id: 'execution',
      name: 'Execution',
      techniques: [
        { id: 'T1574', name: 'Hijack Execution Flow', hit_count: 1, severity: 'medium', detection_ids: [CAPE_DLL_ID] },
      ],
    },
    {
      id: 'privilege-escalation',
      name: 'Privilege Escalation',
      techniques: [
        {
          id: 'T1055',
          name: 'Process Injection',
          hit_count: 2,
          severity: 'critical',
          detection_ids: [CAPE_DLL_ID, SIGMA_ID],
        },
      ],
    },
    {
      id: 'stealth',
      name: 'Stealth',
      techniques: [
        { id: 'T1112', name: 'Modify Registry', hit_count: 1, severity: 'info', detection_ids: [SIGMA_SELFTEST_ID] },
      ],
    },
    {
      id: 'command-and-control',
      name: 'Command and Control',
      techniques: [
        { id: 'T1071', name: 'Application Layer Protocol', hit_count: 1, severity: 'high', detection_ids: [SURICATA_ID] },
      ],
    },
    {
      id: 'unknown',
      name: 'Unknown',
      techniques: [{ id: 'T1999', name: null, hit_count: 1, severity: 'low', detection_ids: [CAPE_RECON_ID] }],
    },
  ],
}

export const EMPTY_ATTACK_MATRIX: AttackMatrix = { attack_version: '19.2', tactics: [] }

export const ARTIFACTS_VIEW: ArtifactsView = {
  dropped: [],
  payloads: [],
  procdumps: [],
  memory_dump: null,
  pcap: null,
  screenshots: [
    { n: 1, name: '0001.jpg', size: 47581 },
    { n: 2, name: '0002.jpg', size: 46918 },
    { n: 3, name: '0003.jpg', size: 55604 },
  ],
  configs: [],
}
