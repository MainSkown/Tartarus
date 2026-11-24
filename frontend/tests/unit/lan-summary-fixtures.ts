import type { LanCredential, LanHostSummary, LanServiceUse, LanSummary, LanWrittenFile } from '@/api'

export const SHA256 = 'ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12'
export const HOSTILE = '<img src=x onerror=alert(1)>'

export function lanService(overrides: Partial<LanServiceUse> = {}): LanServiceUse {
  return {
    service: 'smb',
    port: 445,
    attempts: 5,
    first: '2026-11-23T12:00:20Z',
    last: '2026-11-23T12:00:40Z',
    ...overrides,
  }
}

export function lanCredential(overrides: Partial<LanCredential> = {}): LanCredential {
  return {
    user: 'Administrator',
    domain: 'CORP',
    mechanism: 'ntlm',
    count: 3,
    success: true,
    secret_as_sent: 'Winter2026!',
    ...overrides,
  }
}

export function lanFile(overrides: Partial<LanWrittenFile> = {}): LanWrittenFile {
  return { path: '\\evil.exe', share: 'ADMIN$', size: 61440, sha256: SHA256, ...overrides }
}

export function lanHost(overrides: Partial<LanHostSummary> = {}): LanHostSummary {
  return {
    fqdn: 'fs01.corp.local',
    address: '192.168.150.201',
    role: 'file-server',
    services: [lanService()],
    credentials: [],
    files: [],
    first: '2026-11-23T12:00:20Z',
    last: '2026-11-23T12:00:40Z',
    ...overrides,
  }
}

export function lanSummary(overrides: Partial<LanSummary> = {}): LanSummary {
  const hosts = overrides.hosts ?? [lanHost()]
  return {
    preset: { id: 'small-office', name: 'Small office' },
    hosts,
    totals: { hosts: hosts.length, attempts: 5, credentials: 0, files: 0 },
    truncated: false,
    ...overrides,
  }
}
