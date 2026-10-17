import type { Page, Route } from '@playwright/test'
import type { BuildView, ErrorEnvelope, Guest, GuestProfile, HealthCheckResult } from '../../src/api/types.gen'

/** What the control service lists for the image the fixtures' guests were built from: editions have an index and a name. */
const WINDOWS_MEDIA = {
  file: 'Win11_25H2_Polish_x64.iso',
  size: 8_345_856_000,
  mtime: 1_791_852_244,
  profile: 'windows',
  kind: 'installer',
  version: '10.0.26200',
  build: 26200,
  language: 'pl-PL',
  arch: 'amd64',
  variants: [
    { index: 1, name: 'Windows 11 Home', edition_id: 'Core', arch: 'amd64', languages: ['pl-PL'], default_language: 'pl-PL', build: 26200, installation_type: 'Client' },
    { index: 5, name: 'Windows 11 Pro', edition_id: 'Professional', arch: 'amd64', languages: ['pl-PL'], default_language: 'pl-PL', build: 26200, installation_type: 'Client' },
  ],
}

export const WINDOWS_PROFILE = {
  id: 'windows',
  display_name: 'Windows 11',
  family: 'windows',
  arch: 'x64',
  packages: ['exe', 'dll'],
} as unknown as GuestProfile

const SELFTEST_PASSED = { message: 'every signal was present and no giveaway was found', analysis_id: 41 }

function windowsGuest(name: string, overrides: Partial<Guest> = {}): Guest {
  return {
    name,
    state: 'ready',
    profile: 'windows',
    kind: 'build',
    created: '2026-10-16T09:30:00Z',
    media: { file: 'Win11_25H2_Polish_x64.iso', variant: '5', version: '25H2', language: 'pl-PL', arch: 'x64' },
    options: { defender: true },
    identity: { account: 'Marta', machine: 'DESKTOP-4K7QX2A', password: 'q7Zp-Lm2x-Rv9d' },
    resources: { vcpus: 4, ram_mb: 8192, disk_gb: 80 },
    ip: '192.168.150.10',
    snapshot: 'clean',
    selftest: SELFTEST_PASSED,
    adopted: false,
    giveaways: [],
    badges: ['DEFENDER ON'],
    build_id: `build-${name}`,
    ...overrides,
  }
}

export const LAB1 = windowsGuest('lab1')
export const LAB2 = windowsGuest('lab2', {
  kind: 'clone',
  cloned_from: 'lab1',
  created: '2026-10-16T14:05:00Z',
  identity: { account: 'Marta', machine: 'LAPTOP-9HD3M1P', password: 'n4Vw-Qe8t-Kc2s' },
  ip: '192.168.150.11',
  badges: ['DEFENDER OFF'],
  selftest: { message: 'every signal was present; Defender is off as asked', analysis_id: 52 },
})
export const LAB3 = windowsGuest('lab3', {
  kind: 'clone',
  cloned_from: 'lab1',
  created: '2026-10-17T08:12:00Z',
  identity: { account: 'Marta', machine: 'DESKTOP-R2B8T6W', password: 'x5Yh-Ud3p-Ma7f' },
  ip: '192.168.150.12',
  resources: { vcpus: 2, ram_mb: 4096, disk_gb: 80 },
  badges: ['DEFENDER ON', 'DECOYS'],
  selftest: { message: 'every signal was present and no giveaway was found', analysis_id: 63 },
})
export const LAB4_BUILDING = windowsGuest('lab4', {
  state: 'building',
  kind: 'clone',
  cloned_from: 'lab1',
  created: '2026-10-17T09:40:00Z',
  ip: '192.168.150.13',
  snapshot: null,
  selftest: null,
  identity: { account: 'Marta', machine: 'DESKTOP-J6C1N5Z', password: 'g3Lk-Pr9w-Tb4h' },
  badges: ['DEFENDER OFF'],
  build_id: 'build-lab4',
})
export const LAB5_FAILED = windowsGuest('lab5', {
  state: 'failed',
  error: 'self-test failed: no registry event was recorded for the sample; Defender removed the EICAR file although it should be off',
  snapshot: null,
  selftest: { message: 'no registry event was recorded for the sample', analysis_id: 70 },
  ip: '192.168.150.14',
  badges: ['DEFENDER OFF'],
})
export const ADOPTED = windowsGuest('win', {
  adopted: true,
  created: '2026-10-12T18:00:00Z',
  identity: { account: 'Analyst', machine: 'WIN-GUEST', password: 'Tartarus1!' },
  badges: ['DEFENDER ON'],
  giveaways: ['account "Analyst"', 'folder C:\\tartarus', 'firewall rule "Tartarus agent"', 'computer name WIN-GUEST'],
  selftest: null,
})
export const BROKEN = { name: 'lab9', state: 'broken', error: 'guest.json could not be read: unexpected end of file' } as Guest

export const LONG_NAME = 'windows-11-defender-off-decoys-3'
export const LONG_GUEST = windowsGuest(LONG_NAME, {
  kind: 'clone',
  cloned_from: 'windows-11-defender-on-base-01',
  identity: { account: 'Bartholomew', machine: 'DESKTOP-ABCDEFG', password: 'p'.repeat(64) },
  media: { file: 'long.iso', variant: 'Pro for Workstations N Education Enterprise', version: '25H2', language: 'pl-PL', arch: 'x64' },
  badges: ['DEFENDER OFF', 'DECOYS', 'SYSMON ON', 'KEYBOARD PL-214', 'LANGUAGE PL-PL', 'SECURE BOOT', 'TPM 2.0'],
  selftest: {
    message: 'every signal was present and no giveaway was found in the computer name, the accounts, the services or the folders',
    analysis_id: 118,
  },
})

export const POPULATED: Guest[] = [LAB1, LAB2, LAB3, LAB4_BUILDING, LAB5_FAILED]

export const BUILD_LAB4: BuildView = {
  id: 'build-lab4',
  guest: 'lab4',
  kind: 'clone',
  status: 'running',
  step: 3,
  steps: [],
  percent: 46,
  message: 'Reconfiguring the copy: renaming the computer',
  log: [],
} as unknown as BuildView

export const CHECKS_ONE_FAILED: HealthCheckResult = {
  name: 'lab1',
  checks: [
    { id: 'agent', ok: true, message: 'the agent answers on port 8000' },
    { id: 'snapshot', ok: true, message: 'the snapshot "clean" restores' },
    { id: 'internet', ok: false, message: 'the guest reached 1.1.1.1; it should have no route to the internet' },
    { id: 'dns', ok: true, message: 'DNS is answered by the fake resolver' },
  ],
}

const errorEnvelope = (code: string, message: string): ErrorEnvelope => ({ error: { code, message, details: {} } })

export interface GuestApiMock {
  guests: Guest[]
  /** Delay before `/api/guests` answers, for the loading state. */
  listDelayMs?: number
  /** `/api/guests` answers 502 with this message. */
  listFailure?: string
  checkResult?: HealthCheckResult
  checkRefusal?: string
  deleteRefusal?: string
  /** The check answers only after `release()` is called. */
  holdChecks?: Promise<void>
}

function guestsApiRoute(options: GuestApiMock): (route: Route) => Promise<void> {
  return async (route) => {
    const { pathname } = new URL(route.request().url())
    const method = route.request().method()
    if (pathname === '/api/guests') {
      if (options.listDelayMs) await new Promise((resolve) => setTimeout(resolve, options.listDelayMs))
      if (options.listFailure) {
        await route.fulfill({ status: 502, json: errorEnvelope('guest_control_unreachable', options.listFailure) })
        return
      }
      await route.fulfill({ json: options.guests })
    } else if (pathname === '/api/guests/profiles') {
      await route.fulfill({ json: [WINDOWS_PROFILE] })
    } else if (pathname === '/api/guests/media') {
      await route.fulfill({ json: [WINDOWS_MEDIA] })
    } else if (pathname === '/api/guests/builds/active') {
      await route.fulfill({ status: 404, json: errorEnvelope('not_found', 'no build is running') })
    } else if (pathname.startsWith('/api/guests/builds/')) {
      await route.fulfill({ json: BUILD_LAB4 })
    } else if (pathname.endsWith('/check') && method === 'POST') {
      await options.holdChecks
      if (options.checkRefusal) {
        await route.fulfill({ status: 409, json: errorEnvelope('conflict', options.checkRefusal) })
        return
      }
      await route.fulfill({ json: options.checkResult ?? CHECKS_ONE_FAILED })
    } else if (method === 'DELETE') {
      if (options.deleteRefusal) {
        await route.fulfill({ status: 409, json: errorEnvelope('conflict', options.deleteRefusal) })
        return
      }
      await route.fulfill({ status: 204 })
    } else {
      await route.fallback()
    }
  }
}

export async function mockGuestApi(page: Page, options: GuestApiMock): Promise<void> {
  await page.route((url) => url.pathname.startsWith('/api/guests'), guestsApiRoute(options))
}

/** A promise the test settles by hand, to keep a request in flight while it is photographed. */
export function gate(): { opened: Promise<void>; open: () => void } {
  let open: () => void = () => undefined
  const opened = new Promise<void>((resolve) => (open = resolve))
  return { opened, open }
}
