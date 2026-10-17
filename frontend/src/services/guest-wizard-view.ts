import type { GuestState } from '@/api'

// Measured on the real stack (m6-guest-wizard.md, waves 2 and 3); the build and the clone report their own progress.
const BUILD_MINUTES = 15
const CLONE_MINUTES = 5
const CLONE_DISK_GB = 22

export function cloneSummary(sourceName: string): string {
  return `Copies ${sourceName}'s disk, gives the copy its own identity, takes about ${CLONE_MINUTES} minutes and about ${CLONE_DISK_GB} GB.`
}

export function blockingWarning(kind: 'build' | 'clone'): string {
  const minutes = kind === 'build' ? BUILD_MINUTES : CLONE_MINUTES
  return `The ${kind} takes about ${minutes} minutes. No analysis can start until it is done.`
}

export function sourceNotReadyMessage(name: string, state: GuestState): string {
  return `${name} is ${state}: only a ready guest can be cloned.`
}
