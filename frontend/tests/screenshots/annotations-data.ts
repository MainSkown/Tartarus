import type { Annotations, NoteAnnotation, TagAnnotation, TagUsageRead } from '../../src/api/types.gen'
import { MIXED_ANALYSES } from './fixtures'

export const ANALYSIS_ID = 45
export const ALERT_EVENT = '0090624136bb0fdbc2b65be9'
export const NETWORK_EVENT = '66b348f3796e6ff8301c425d'
export const LONG_TAG = 'a-tag-name-of-exactly-forty-characters-x'

let nextId = 1

export function tag(name: string, target_type: TagAnnotation['target_type'] = 'analysis', target_ref = '', orphaned = false): TagAnnotation {
  return { link_id: nextId++, tag: name, target_type, target_ref, orphaned }
}

export function note(body: string, target_type: NoteAnnotation['target_type'] = 'analysis', target_ref = '', orphaned = false): NoteAnnotation {
  return { id: nextId++, target_type, target_ref, body, created_at: '2026-10-14T10:00:00Z', updated_at: '2026-10-14T10:00:00Z', orphaned }
}

export const USAGE: TagUsageRead[] = [
  { name: 'phishing', count: 7 },
  { name: 'emotet', count: 4 },
  { name: 'tlp:amber', count: 3 },
  { name: 'needs-review', count: 2 },
  { name: 'dropper', count: 2 },
  { name: 'clean-baseline', count: 1 },
  { name: LONG_TAG, count: 1 },
]

/** The Dashboard's mixed analyses with tags on some: two tags, three (one folds into +N), one long name, none. */
export const TAGGED_ANALYSES = MIXED_ANALYSES.map((analysis) => {
  const tags: Record<number, string[]> = {
    8: ['phishing'],
    6: ['phishing', 'emotet', 'tlp:amber'],
    5: ['needs-review', 'dropper'],
    4: ['clean-baseline'],
    3: [LONG_TAG],
  }
  return { ...analysis, tags: tags[analysis.id] ?? [] }
})

/** Enough text for a 20 000-character note: paragraphs of plausible analyst prose, cut at the limit. */
export function twentyThousandCharacters(): string {
  const paragraph =
    'The sample unpacks itself in memory, injects into explorer.exe and beacons to c2.evil-updates.net every 30 seconds over HTTPS with a 15 percent jitter. '
  return `${paragraph.repeat(200)}\n`.repeat(1).slice(0, 20_000)
}

export function analysisAnnotations(overrides: Partial<Annotations> = {}): Annotations {
  return { tags: [], notes: [], ...overrides }
}

/** Tags and notes on all three targets, with one event and one process that are gone from the analysis. */
export function populatedAnnotations(eventIds: [string, string]): Annotations {
  return {
    tags: [
      tag('phishing'),
      tag('emotet'),
      tag('tlp:amber'),
      tag('dropper', 'process', '9708'),
      tag('c2', 'event', eventIds[0]),
      tag('needs-review', 'event', eventIds[1]),
      tag('stale', 'process', '31337', true),
      tag('old-finding', 'event', 'deadbeefdeadbeefdeadbeef', true),
    ],
    notes: [
      note('Invoice lure from a spoofed supplier address. Drops a second stage from a pastebin URL and persists through a Run key.'),
      note('Unpacks in memory, then spawns cmd.exe for host discovery.\nCheck the injected thread against the memory dump.', 'process', '9708'),
      note('Beacon every 30 seconds with jitter; the domain matches the Emotet epoch 5 list.', 'event', eventIds[0]),
      note('The process this note was written on is not in the analysis any more after a re-ingest.', 'process', '31337', true),
      note('Event vanished in the re-ingest, kept for the report.', 'event', 'deadbeefdeadbeefdeadbeef', true),
    ],
  }
}
