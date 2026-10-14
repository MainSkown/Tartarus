import type { Event } from '@/api'

/** What the process chip shows for an event; nothing when the event names no process by pid. */
export function eventProcess(event: Event): { pid: number; name: string | null } | null {
  const pid = event.process?.pid
  return pid === null || pid === undefined ? null : { pid, name: event.process?.name ?? null }
}

/** The one line that stands for an event where there is room for one: its summary, else its action, else its id. */
export function eventTitle(event: Event): string {
  return event.summary || event.action || event.id
}
