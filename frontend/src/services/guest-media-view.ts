import type { MediaEntry, MediaVariant } from '@/api'
import { t } from '@/i18n'

/** The host folder the installation images are read from; a path, shown as it is. */
export const ISO_FOLDER = 'data/iso'

export function variantLabel(variant: Pick<MediaVariant, 'name' | 'default_language'>, mediaLanguage: string | null | undefined): string {
  return [variant.name, variant.default_language ?? mediaLanguage].filter(Boolean).join(' · ')
}

export function editionCount(entry: MediaEntry): string | undefined {
  const count = entry.variants?.length ?? 0
  if (count === 0) return undefined
  return t('guests.media.editions', count)
}

/** What the scan read from an image, in the order a person compares images by. */
export function mediaDetails(entry: MediaEntry): string[] {
  const buildAlreadyInVersion = entry.build != null && entry.version?.includes(String(entry.build))
  const build = entry.build != null && !buildAlreadyInVersion ? t('guests.media.build', { number: entry.build }) : undefined
  return [entry.version, build, entry.language, entry.arch, editionCount(entry)].filter((part): part is string => Boolean(part))
}
