import type { GuestState } from '@/api'
import { t, type MessageKey } from '@/i18n'

// Measured on the real stack (m6-guest-wizard.md, waves 2 and 3); the build and the clone report their own progress.
const BUILD_MINUTES = 15
const CLONE_MINUTES = 5
const CLONE_DISK_GB = 22

const KIND_NOUN: Record<'build' | 'clone', MessageKey> = { build: 'guests.wizard.noun.build', clone: 'guests.wizard.noun.clone' }

export function cloneSummary(sourceName: string): string {
  return t('guests.wizard.cloneSummary', { source: sourceName, minutes: CLONE_MINUTES, disk: CLONE_DISK_GB })
}

export function blockingWarning(kind: 'build' | 'clone'): string {
  const minutes = kind === 'build' ? BUILD_MINUTES : CLONE_MINUTES
  return t('guests.wizard.blockingWarning', { kind: t(KIND_NOUN[kind]), minutes })
}

export function sourceNotReadyMessage(name: string, state: GuestState): string {
  return t('guests.wizard.notReady', { name, state })
}
