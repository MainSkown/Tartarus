import type { BuildView, Guest, GuestProfile } from '@/api'

export function guestFixture(overrides: Partial<Guest> = {}): Guest {
  return {
    name: 'lab1',
    state: 'ready',
    profile: 'windows',
    kind: 'build',
    created: '2026-10-16T09:30:00Z',
    media: { file: 'Win11_25H2.iso', variant: 'Pro', version: '25H2', language: 'pl-PL', arch: 'x64' },
    options: { defender: true },
    identity: { account: 'Marta', machine: 'DESKTOP-4K7QX2A', password: 'q7Zp-Lm2x-Rv9' },
    resources: { vcpus: 4, ram_mb: 8192, disk_gb: 80 },
    ip: '192.168.150.10',
    snapshot: 'clean',
    selftest: { message: 'all signals present', analysis_id: 41 },
    adopted: false,
    giveaways: [],
    badges: ['DEFENDER ON'],
    build_id: 'b-lab1',
    ...overrides,
  }
}

export const WINDOWS_PROFILE = { id: 'windows', display_name: 'Windows 11' } as GuestProfile

export function buildFixture(overrides: Partial<BuildView> = {}): BuildView {
  return {
    id: 'b-lab4',
    guest: 'lab4',
    kind: 'clone',
    status: 'running',
    step: 3,
    steps: [],
    percent: 42,
    message: 'Provisioning the guest',
    log: [],
    ...overrides,
  } as BuildView
}
