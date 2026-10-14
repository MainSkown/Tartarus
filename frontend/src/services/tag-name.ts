export const MAX_TAG_NAME_LENGTH = 40

const PART = /^[a-z0-9._-]+$/

export type TagNameCheck = { name: string } | { problem: string | null }

/**
 * The backend's tag rule (app/annotations/validation.py), checked before a request is sent. A
 * `problem` of null is an empty input: nothing to add and nothing to complain about.
 */
export function checkTagName(raw: string): TagNameCheck {
  const name = raw.trim().toLowerCase()
  if (name === '') return { problem: null }
  if (name.length > MAX_TAG_NAME_LENGTH) return { problem: `at most ${MAX_TAG_NAME_LENGTH} characters` }
  const parts = name.split(':')
  if (parts.length > 2 || parts.some((part) => part === '')) return { problem: "one ':' at most, between two parts" }
  if (!parts.every((part) => PART.test(part))) return { problem: "only a-z, 0-9, '.', '_' and '-'" }
  return { name }
}
