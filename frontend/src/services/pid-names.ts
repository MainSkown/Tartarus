import type { Event } from '@/api'

/** The image name of each wanted pid, as far as the listed events say; a pid whose name is not among them is left out. */
export function pidNamesOf(events: Event[], pids: number[]): Record<number, string> {
  const names: Record<number, string> = {}
  if (pids.length === 0) return names
  for (const { process } of events) {
    const pid = process?.pid
    if (process?.name && pid != null && pids.includes(pid) && !(pid in names)) names[pid] = process.name
  }
  return names
}
