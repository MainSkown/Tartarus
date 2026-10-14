import type { Severity } from '@/api'
import { SEVERITIES, severityMeta } from '@/services/analysis-status'
import { LANE_ORDER, laneMeta } from '@/services/lanes'

/** The colours and font the canvas draws with, all of them design-system tokens read once rather than written here. */
export interface TimelinePalette {
  background: string
  grid: string
  axisText: string
  labelText: string
  text: string
  onAccent: string
  accent: string
  accentLight: string
  fontMono: string
  lane: Record<string, string>
  severity: Record<Severity, string>
}

/** `read` returns the value of a CSS custom property by name, e.g. `--dark-bg`. */
export function readTimelinePalette(read: (token: string) => string): TimelinePalette {
  return {
    background: read('--dark-bg'),
    grid: read('--border-subtle'),
    axisText: read('--text-gray-dark'),
    labelText: read('--text-gray'),
    text: read('--text-white'),
    onAccent: read('--text-on-primary'),
    accent: read('--blue-primary'),
    accentLight: read('--blue-light'),
    fontMono: read('--font-mono'),
    lane: Object.fromEntries(LANE_ORDER.map((lane) => [lane, read(laneMeta(lane).color)])),
    severity: Object.fromEntries(SEVERITIES.map((severity) => [severity, read(severityMeta(severity).color)])) as Record<Severity, string>,
  }
}
