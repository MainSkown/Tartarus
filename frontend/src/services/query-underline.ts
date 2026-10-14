import type { QueryErrorRead } from '@/api'

export interface UnderlineSegment {
  text: string
  error?: QueryErrorRead
}

interface Span {
  start: number
  end: number
  error: QueryErrorRead
}

/** The error's span inside the text; one that is empty is widened to a character so it can be seen. */
function visibleSpan(error: QueryErrorRead, length: number): Span | undefined {
  const start = Math.max(0, error.start)
  if (start > length) return undefined
  const end = Math.min(length, error.end)
  if (end > start) return { start, end, error }
  if (start < length) return { start, end: start + 1, error }
  return length > 0 ? { start: length - 1, end: length, error } : undefined
}

/**
 * Cuts the text into pieces that are underlined (they carry the error) and pieces that are not.
 * Where two errors overlap, the earlier one keeps the shared stretch.
 */
export function underlineSegments(text: string, errors: QueryErrorRead[]): UnderlineSegment[] {
  const spans = errors
    .map((error) => visibleSpan(error, text.length))
    .filter((span) => span !== undefined)
    .sort((a, b) => a.start - b.start || a.end - b.end)

  const segments: UnderlineSegment[] = []
  let cursor = 0
  for (const span of spans) {
    const start = Math.max(span.start, cursor)
    if (span.end <= start) continue
    if (start > cursor) segments.push({ text: text.slice(cursor, start) })
    segments.push({ text: text.slice(start, span.end), error: span.error })
    cursor = span.end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) })
  return segments
}

/** The text with the error's span replaced by its "did you mean" suggestion. */
export function applyErrorSuggestion(text: string, error: QueryErrorRead): string {
  if (error.suggestion === null) return text
  return `${text.slice(0, Math.max(0, error.start))}${error.suggestion}${text.slice(Math.max(0, error.end))}`
}
