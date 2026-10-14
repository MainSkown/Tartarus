import type { Annotations, NoteAnnotation, TagAnnotation } from '@/api'

let nextId = 1

export function tagAnnotation(overrides: Partial<TagAnnotation> = {}): TagAnnotation {
  return { link_id: nextId++, tag: 'phishing', target_type: 'analysis', target_ref: '', orphaned: false, ...overrides }
}

export function noteAnnotation(overrides: Partial<NoteAnnotation> = {}): NoteAnnotation {
  return {
    id: nextId++,
    target_type: 'analysis',
    target_ref: '',
    body: 'Drops a second stage from a pastebin URL.',
    created_at: '2026-10-14T10:00:00Z',
    updated_at: '2026-10-14T10:00:00Z',
    orphaned: false,
    ...overrides,
  }
}

export function annotations(tags: TagAnnotation[] = [], notes: NoteAnnotation[] = []): Annotations {
  return { tags, notes }
}

export const succeeded = <T>(data: T) => ({ data, error: undefined })

export function failed(message: string, status: number, details: Record<string, unknown> = {}) {
  return { data: undefined, error: { error: { code: 'error', message, details } }, response: { status } }
}
