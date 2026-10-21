import type { Page, Route } from '@playwright/test'
import type { ErrorEnvelope, Guest, GuestProfile, MediaEntry, ProfileOption } from '../../src/api/types.gen'

export const LONG_MEDIA_FILE =
  'Win11_25H2_Polish_x64_v2_enterprise_evaluation_with_all_updates_integrated_2026-09-patch-tuesday_checked_release.iso'
export const LONG_OPTION_HELP =
  'Your choice, on by default. Left on, a sample meets Defender the way it would on a real machine, and you see how it gets past it. Off suits samples that Defender would remove before they run, or that behave differently when it is running; the build then turns Tamper Protection off with a scripted step and checks it with a test file.'

const DEFENDER: ProfileOption = {
  key: 'defender',
  label: 'Microsoft Defender',
  type: 'bool',
  default: true,
  help: LONG_OPTION_HELP,
  requires_user_step: false,
  changeable_on_clone: true,
}
const DECOYS: ProfileOption = {
  key: 'decoys',
  label: 'Make it look used',
  type: 'bool',
  default: false,
  help: 'Adds documents, downloads, pictures, shortcuts and a recent-files trail with dates spread over the past months, so the machine does not look freshly installed.',
  changeable_on_clone: true,
}
const SYSMON: ProfileOption = {
  key: 'sysmon',
  label: 'Sysmon',
  type: 'bool',
  default: true,
  help: 'Installs Sysmon with the pinned, low-volume configuration and checks that its service runs and logs.',
}
const KEY: ProfileOption = {
  key: 'key',
  label: 'Product key',
  type: 'secret',
  default: '',
  help: 'Optional, XXXXX-XXXXX-XXXXX-XXXXX-XXXXX. Without one Windows installs unactivated.',
}
const KEYBOARD: ProfileOption = {
  key: 'keyboard',
  label: 'Keyboard layout',
  type: 'choice',
  default: 'Polish (Programmers)',
  choices: ['Polish (Programmers)', 'Polish (214)', 'US', 'UK', 'German', 'French', 'Spanish', 'Czech', 'Italian', 'Russian', 'Ukrainian'],
  help: 'The layout Windows is installed with.',
}
export const MANUAL_STEP_OPTION: ProfileOption = {
  key: 'activation',
  label: 'Activate with a phone code',
  type: 'string',
  default: '',
  help: 'Enter the installation code if you want the build to activate Windows by phone.',
  requires_user_step: true,
}

export function windowsProfile(options: ProfileOption[] = [DEFENDER, DECOYS, SYSMON, KEY, KEYBOARD]): GuestProfile {
  return {
    id: 'windows',
    display_name: 'Windows',
    family: 'windows',
    arch: 'x64',
    resources: { vcpus: 2, ram_mb: 4096, disk_gb: 80, min_disk_gb: 64 },
    media: { kinds: ['installer'] },
    options,
    identity: {
      account: { label: 'Username', pattern: '[A-Za-z][A-Za-z0-9_-]{0,19}', reserved: ['Administrator', 'Guest'], generator: 'first_name', optional: true },
      machine: {
        label: 'Computer name',
        pattern: '(?!\\d+$)[A-Za-z0-9]([A-Za-z0-9-]{0,13}[A-Za-z0-9])?',
        reserved: ['localhost'],
        generator: 'computer_name',
        optional: true,
      },
      password: { label: 'Password', pattern: '[\\x20-\\x7e]{8,64}', reserved: [], generator: 'password', optional: true },
    },
    clone: { computer_name_editable: true },
    badges: [],
    packages: ['exe', 'dll'],
    agent: { interactive: { options: 'interactive=1,nohuman=yes', task_fields: {} } },
    selftest: { sample: { source: 'benign.c', build: [], output: 'benign.exe' }, signals: [], extras: [] },
  } as unknown as GuestProfile
}

function medium(overrides: Partial<MediaEntry> = {}): MediaEntry {
  return {
    file: 'Win11_25H2_Polish_x64_v2.iso',
    size: 7_800_000_000,
    mtime: 1_760_000_000,
    profile: 'windows',
    kind: 'installer',
    variants: [
      { index: 1, name: 'Windows 11 Home', edition_id: 'Core', languages: ['pl-PL'], default_language: 'pl-PL' },
      { index: 5, name: 'Windows 11 Pro', edition_id: 'Professional', languages: ['pl-PL'], default_language: 'pl-PL' },
      { index: 6, name: 'Windows 11 Pro N', edition_id: 'ProfessionalN', languages: ['pl-PL'], default_language: 'pl-PL' },
    ],
    version: '10.0.26200',
    build: 26200,
    language: 'pl-PL',
    arch: 'x64',
    error: null,
    ...overrides,
  }
}

export const MEDIA_PL = medium()
export const MEDIA_EN = medium({
  file: 'Win11_25H2_English_x64_v2.iso',
  size: 7_400_000_000,
  language: 'en-US',
  variants: [{ index: 1, name: 'Windows 11 Pro', edition_id: 'Professional', languages: ['en-US'], default_language: 'en-US' }],
})
export const MEDIA_BROKEN = medium({
  file: 'backup-2026.iso',
  size: 1_200_000,
  profile: null,
  kind: null,
  variants: [],
  version: null,
  build: null,
  language: null,
  arch: null,
  error: 'not an installation image: no install.wim or install.esd found',
})
export const MEDIA_LONG_NAME = medium({ file: LONG_MEDIA_FILE })
export const MEDIA_UNREAD = medium({ file: 'ubuntu-24.04-desktop.iso', size: 6_100_000_000, profile: 'ubuntu', variants: [] })

function sourceGuest(overrides: Partial<Guest> & Pick<Guest, 'name' | 'state'>): Guest {
  return {
    profile: 'windows',
    kind: 'build',
    options: { defender: true, decoys: false, sysmon: true, key: '', keyboard: 'Polish (Programmers)' },
    identity: { account: 'Marta', machine: 'DESKTOP-4K7QX2A', password: 'q7Zp-Lm2x-Rv9d' },
    resources: { vcpus: 4, ram_mb: 8192, disk_gb: 80 },
    badges: ['DEFENDER ON'],
    ...overrides,
  }
}

export const SOURCE_READY = sourceGuest({ name: 'lab1', state: 'ready' })
export const SOURCE_DEFENDER_OFF = sourceGuest({
  name: 'lab2',
  state: 'ready',
  options: { defender: false, decoys: true, sysmon: true, key: '', keyboard: 'US' },
  badges: ['DEFENDER OFF', 'DECOYS'],
})
export const SOURCE_BUILDING = sourceGuest({ name: 'lab4', state: 'building', badges: [] })
export const SOURCE_LONG_NAME = sourceGuest({
  name: 'malware-lab-windows-11-enterprise-defender-off-no-decoys-clone-of-lab1',
  state: 'ready',
})

const envelope = (code: string, message: string, fields: { field: string; message: string }[] = []): ErrorEnvelope => ({
  error: {
    code,
    message,
    details: { fields: fields.map(({ field, message: text }) => ({ location: ['body', field], message: text, type: 'rejected' })) },
  },
})

export const GIVEAWAY_422 = envelope('validation_error', 'Request validation failed', [
  { field: 'identity.machine', message: "contains 'test', which tells a sample what the machine is" },
])
export const NAME_TAKEN_422 = envelope('validation_error', 'Request validation failed', [
  { field: 'name', message: 'is already used by another guest' },
])
export const CONFLICT_409 = envelope('conflict', 'Another guest is being built: lab4. Only one build runs at a time.')
export const ANALYSIS_ACTIVE_409 = envelope('conflict', 'An analysis is queued or running; a build starts when it has finished')

export interface Refusal {
  status: number
  body: ErrorEnvelope
}

export interface WizardApiMock {
  media?: MediaEntry[]
  profiles?: GuestProfile[]
  guests?: Guest[]
  /** `/api/guests/media` answers only after this resolves. */
  mediaGate?: Promise<void>
  mediaFailure?: string
  /** `/api/guests` answers only after this resolves. */
  listGate?: Promise<void>
  /** What the start-build and clone POSTs answer instead of 202. */
  startRefusal?: Refusal
  /** The start-build and clone POSTs answer only after this resolves. */
  startGate?: Promise<void>
}

export function gate(): { opened: Promise<void>; open: () => void } {
  let open: () => void = () => undefined
  const opened = new Promise<void>((resolve) => (open = resolve))
  return { opened, open }
}

function wizardRoute(options: WizardApiMock): (route: Route) => Promise<void> {
  return async (route) => {
    const { pathname } = new URL(route.request().url())
    const method = route.request().method()
    if (pathname === '/api/guests/media') {
      await options.mediaGate
      if (options.mediaFailure) {
        await route.fulfill({ status: 502, json: envelope('bad_gateway', options.mediaFailure) })
        return
      }
      await route.fulfill({ json: options.media ?? [MEDIA_PL, MEDIA_EN, MEDIA_BROKEN] })
    } else if (pathname === '/api/guests/profiles') {
      await route.fulfill({ json: options.profiles ?? [windowsProfile()] })
    } else if (pathname === '/api/guests') {
      await options.listGate
      await route.fulfill({ json: options.guests ?? [SOURCE_READY] })
    } else if (method === 'POST' && (pathname === '/api/guests/build' || pathname.endsWith('/clone'))) {
      await options.startGate
      if (options.startRefusal) {
        await route.fulfill({ status: options.startRefusal.status, json: options.startRefusal.body })
        return
      }
      await route.fulfill({ status: 202, json: { job_id: 12, build_id: 'build-lab5', guest: 'lab5' } })
    } else if (pathname.startsWith('/api/guests/builds')) {
      await route.fulfill({ status: 404, json: envelope('not_found', 'no build is running') })
    } else {
      await route.fallback()
    }
  }
}

export async function mockWizardApi(page: Page, options: WizardApiMock = {}): Promise<void> {
  await page.route((url) => url.pathname.startsWith('/api/guests'), wizardRoute(options))
}
