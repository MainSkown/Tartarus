/** The fields the facet panel offers, in the order it shows them. */
export const FACET_FIELDS = ['process.name', 'tartarus.lane', 'event.action', 'api.name', 'destination.domain', 'rule.name']

const SHORT_LABELS: Record<string, string> = {
  'process.name': 'PROCESS',
  'tartarus.lane': 'LANE',
  'event.action': 'ACTION',
  'api.name': 'API',
  'destination.domain': 'DOMAIN',
  'rule.name': 'RULE',
}

/** A short heading for a field where one reads better than the dotted name; the name in capitals otherwise. */
export function fieldLabel(field: string): string {
  return SHORT_LABELS[field] ?? field.toUpperCase()
}
