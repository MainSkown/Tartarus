import type { NoteAnnotation, TagAnnotation } from '@/api'
import type { AnnotationTarget } from '@/stores/annotations'

export interface AnnotationEntry {
  target: AnnotationTarget
  orphaned: boolean
  tags: TagAnnotation[]
  notes: NoteAnnotation[]
}

export interface AnnotationGroups {
  analysis: AnnotationEntry | undefined
  processes: AnnotationEntry[]
  events: AnnotationEntry[]
}

type Annotation = TagAnnotation | NoteAnnotation

function entryFor(entries: Map<string, AnnotationEntry>, annotation: Annotation): AnnotationEntry {
  const key = `${annotation.target_type}\u0000${annotation.target_ref}`
  let entry = entries.get(key)
  if (!entry) {
    entry = {
      target: { type: annotation.target_type, ref: annotation.target_ref },
      orphaned: annotation.orphaned,
      tags: [],
      notes: [],
    }
    entries.set(key, entry)
  }
  return entry
}

/** Every tag and note of an analysis as one entry per target: the analysis, each pid, each event. */
export function groupAnnotations(tags: TagAnnotation[], notes: NoteAnnotation[]): AnnotationGroups {
  const entries = new Map<string, AnnotationEntry>()
  for (const tag of tags) entryFor(entries, tag).tags.push(tag)
  for (const note of notes) entryFor(entries, note).notes.push(note)
  const all = [...entries.values()]
  const ofType = (type: AnnotationTarget['type']) => all.filter((entry) => entry.target.type === type)
  return {
    analysis: ofType('analysis')[0],
    processes: ofType('process').sort((a, b) => Number(a.target.ref) - Number(b.target.ref)),
    events: ofType('event'),
  }
}
