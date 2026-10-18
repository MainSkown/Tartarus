import { t, type MessageKey } from '@/i18n'
export interface LaneMeta {
  label: string
  /** Name of a CSS custom property from app.css, without the `var()` wrapper. */
  color: string
  /** Material Icons name. */
  icon: string
}

export interface LaneBar extends LaneMeta {
  lane: string
  count: number
  /** The lane's count as a fraction of the busiest lane's, from 0 to 1. */
  share: number
}

interface LaneStyle extends Omit<LaneMeta, 'label'> {
  labelKey: MessageKey
}

// The design system fixes this order; a seventh category goes into the neutral api lane.
const LANE_STYLE: Record<string, LaneStyle> = {
  process: { labelKey: 'timeline.lane.process', color: '--cat-process', icon: 'terminal' },
  file: { labelKey: 'timeline.lane.file', color: '--cat-file', icon: 'description' },
  registry: { labelKey: 'timeline.lane.registry', color: '--cat-registry', icon: 'account_tree' },
  network: { labelKey: 'timeline.lane.network', color: '--cat-network', icon: 'lan' },
  memory: { labelKey: 'timeline.lane.memory', color: '--cat-memory', icon: 'memory' },
  api: { labelKey: 'timeline.lane.api', color: '--cat-api', icon: 'functions' },
}

export const LANE_ORDER = Object.keys(LANE_STYLE)

export function laneMeta(lane: string): LaneMeta {
  const style = LANE_STYLE[lane]
  if (style) return { label: t(style.labelKey), color: style.color, icon: style.icon }
  const neutral = LANE_STYLE.api!
  return { label: lane.toUpperCase(), color: neutral.color, icon: neutral.icon }
}

function laneRank(lane: string): number {
  const rank = LANE_ORDER.indexOf(lane)
  return rank === -1 ? LANE_ORDER.length : rank
}

export function laneBars(counts: Record<string, number> | undefined): LaneBar[] {
  const lanes = Object.entries(counts ?? {}).filter(([, count]) => count > 0)
  const busiest = Math.max(...lanes.map(([, count]) => count))
  return lanes
    .sort(([a], [b]) => laneRank(a) - laneRank(b) || a.localeCompare(b))
    .map(([lane, count]) => ({ lane, count, share: count / busiest, ...laneMeta(lane) }))
}
