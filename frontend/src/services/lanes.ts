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

// The design system fixes this order; a seventh category goes into the neutral api lane.
const LANE_META: Record<string, LaneMeta> = {
  process: { label: 'PROCESS', color: '--cat-process', icon: 'terminal' },
  file: { label: 'FILE', color: '--cat-file', icon: 'description' },
  registry: { label: 'REGISTRY', color: '--cat-registry', icon: 'account_tree' },
  network: { label: 'NETWORK', color: '--cat-network', icon: 'lan' },
  memory: { label: 'MEMORY', color: '--cat-memory', icon: 'memory' },
  api: { label: 'API', color: '--cat-api', icon: 'functions' },
}

export const LANE_ORDER = Object.keys(LANE_META)

export function laneMeta(lane: string): LaneMeta {
  return LANE_META[lane] ?? { ...LANE_META.api!, label: lane.toUpperCase() }
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
