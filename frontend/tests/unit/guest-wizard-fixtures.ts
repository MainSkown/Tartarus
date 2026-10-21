import type { GuestProfile, MediaEntry, ProfileOption } from '@/api'

export const DEFENDER_OPTION: ProfileOption = {
  key: 'defender',
  label: 'Microsoft Defender',
  type: 'bool',
  default: true,
  help: 'Your choice, on by default. Left on, a sample meets Defender the way it would on a real machine.',
  changeable_on_clone: true,
}
export const DECOYS_OPTION: ProfileOption = {
  key: 'decoys',
  label: 'Make it look used',
  type: 'bool',
  default: false,
  help: 'Adds documents, downloads and a recent-files trail.',
  changeable_on_clone: true,
}
export const SYSMON_OPTION: ProfileOption = { key: 'sysmon', label: 'Sysmon', type: 'bool', default: true, help: 'Installs Sysmon.' }
export const KEY_OPTION: ProfileOption = {
  key: 'key',
  label: 'Product key',
  type: 'secret',
  default: '',
  help: 'Optional. Without one Windows installs unactivated.',
}
export const KEYBOARD_OPTION: ProfileOption = {
  key: 'keyboard',
  label: 'Keyboard layout',
  type: 'choice',
  default: 'Polish (Programmers)',
  choices: ['Polish (Programmers)', 'US', 'German'],
  help: 'The layout Windows is installed with.',
}
export const HOSTNAME_OPTION: ProfileOption = {
  key: 'banner',
  label: 'Login banner',
  type: 'string',
  default: 'welcome',
  help: 'Shown before login.',
  requires_user_step: true,
}

export function windowsProfile(overrides: Partial<GuestProfile> = {}): GuestProfile {
  return {
    id: 'windows',
    display_name: 'Windows',
    family: 'windows',
    arch: 'x64',
    resources: { vcpus: 2, ram_mb: 4096, disk_gb: 80, min_disk_gb: 64 },
    media: { kinds: ['installer'] },
    options: [DEFENDER_OPTION, DECOYS_OPTION, SYSMON_OPTION, KEY_OPTION, KEYBOARD_OPTION],
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
    ...overrides,
  } as unknown as GuestProfile
}

export function mediaEntry(overrides: Partial<MediaEntry> = {}): MediaEntry {
  return {
    file: 'Win11_25H2_Polish_x64_v2.iso',
    size: 7_800_000_000,
    mtime: 1_760_000_000,
    profile: 'windows',
    kind: 'installer',
    variants: [
      { index: 1, name: 'Windows 11 Home', edition_id: 'Core', languages: ['pl-PL'], default_language: 'pl-PL' },
      { index: 5, name: 'Windows 11 Pro', edition_id: 'Professional', languages: ['pl-PL'], default_language: 'pl-PL' },
    ],
    version: '10.0.26200',
    build: 26200,
    language: 'pl-PL',
    arch: 'x64',
    error: null,
    ...overrides,
  }
}

export const BROKEN_MEDIA = mediaEntry({
  file: 'notes.iso',
  size: 1_200_000,
  profile: null,
  kind: null,
  variants: [],
  version: null,
  build: null,
  language: null,
  arch: null,
  error: 'not a Windows installation image: no install.wim or install.esd found',
})
