import { t, type MessageKey } from '@/i18n'

/** The fields the facet panel offers, in the order it shows them. */
export const FACET_FIELDS = ['process.name', 'tartarus.lane', 'event.action', 'api.name', 'destination.domain', 'rule.name']

const SHORT_LABEL_KEYS: Record<string, MessageKey> = {
  'process.name': 'events.column.process',
  'tartarus.lane': 'events.column.lane',
  'event.action': 'events.column.action',
  'api.name': 'events.column.api',
  'destination.domain': 'events.column.domain',
  'rule.name': 'events.column.rule',
}

/** A short heading for a field where one reads better than the dotted name; the name in capitals otherwise. */
export function fieldLabel(field: string): string {
  const key = SHORT_LABEL_KEYS[field]
  return key === undefined ? field.toUpperCase() : t(key)
}
