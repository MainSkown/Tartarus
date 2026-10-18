import { t } from '@/i18n'

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
  if (name.length > MAX_TAG_NAME_LENGTH) return { problem: t('tags.check.tooLong', { max: MAX_TAG_NAME_LENGTH }) }
  const parts = name.split(':')
  if (parts.length > 2 || parts.some((part) => part === '')) return { problem: t('tags.check.separator') }
  if (!parts.every((part) => PART.test(part))) return { problem: t('tags.check.characters') }
  return { name }
}
