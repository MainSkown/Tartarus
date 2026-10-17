import type { Page } from '@playwright/test'
import type { ErrorEnvelope, Guest, GuestProfile } from '../../src/api/types.gen'

const LONG_GUEST_NAME = 'malware-lab-windows-11-enterprise-defender-off-no-decoys-clone-of-lab1'

function guest(overrides: Partial<Guest> & Pick<Guest, 'name' | 'state'>): Guest {
  return { profile: 'windows', badges: [], ...overrides }
}

export const GUEST_DEFENDER_ON = guest({ name: 'win11-clean', state: 'ready', badges: ['DEFENDER ON'] })
export const GUEST_DEFENDER_OFF = guest({ name: 'win11-lab', state: 'ready', badges: ['DEFENDER OFF'] })
export const GUEST_BUILDING = guest({ name: 'win11-next', state: 'building' })
export const GUEST_FAILED = guest({ name: 'win10-old', state: 'failed', error: 'the scripted step could not find Tamper Protection' })
export const GUEST_LONG_NAME = guest({ name: LONG_GUEST_NAME, state: 'ready', badges: ['DEFENDER OFF'] })
export const GUEST_LINUX = guest({ name: 'ubuntu-box', state: 'ready', profile: 'ubuntu' })

export const ALL_GUESTS: Guest[] = [GUEST_DEFENDER_ON, GUEST_DEFENDER_OFF, GUEST_BUILDING, GUEST_FAILED, GUEST_LONG_NAME]

function profile(id: string, displayName: string, family: string, packages: string[]): GuestProfile {
  return { id, display_name: displayName, family, packages } as GuestProfile
}

export const PROFILES: GuestProfile[] = [
  profile('windows', 'Windows 11', 'windows', ['exe', 'dll', 'doc', 'xls', 'ps1', 'js', 'msi', 'hta']),
  profile('ubuntu', 'Ubuntu 24.04', 'linux', ['bash', 'elf']),
]

export interface GuestsMockOptions {
  guests?: Guest[]
  profiles?: GuestProfile[]
  listError?: { status: number; body: ErrorEnvelope }
}

/** Serves `/api/guests` and `/api/guests/profiles`; a spec that opens the dialog or Settings needs it, since the store loads both. */
export async function mockGuests(page: Page, options: GuestsMockOptions = {}): Promise<void> {
  await page.route(
    (url) => url.pathname === '/api/guests',
    async (route) => {
      if (options.listError) await route.fulfill({ status: options.listError.status, json: options.listError.body })
      else await route.fulfill({ json: options.guests ?? ALL_GUESTS })
    },
  )
  await page.route(
    (url) => url.pathname === '/api/guests/profiles',
    (route) => route.fulfill({ json: options.profiles ?? PROFILES }),
  )
}
