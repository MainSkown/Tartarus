/**
 * Per-viewer conveniences (a collapsed panel, chosen columns) kept in the browser. Storage can be
 * blocked, full or empty in a private window, so a read falls back and a write is best effort:
 * the page must work without it.
 */
export function readStored<T>(key: string, fallback: T, isValid: (value: unknown) => boolean = () => true): T {
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === null) return fallback
    const value: unknown = JSON.parse(raw)
    return isValid(value) ? (value as T) : fallback
  } catch {
    return fallback
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Nothing to do: the choice just is not remembered.
  }
}
