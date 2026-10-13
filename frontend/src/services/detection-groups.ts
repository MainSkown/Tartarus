import type { Detection, DetectionGroup } from '@/api'
import { compareSeverity } from '@/services/analysis-status'

const RULESET_ORDER = ['sigma', 'cape', 'yara', 'suricata']

function rulesetRank(ruleset: string): number {
  const rank = RULESET_ORDER.indexOf(ruleset)
  return rank === -1 ? RULESET_ORDER.length : rank
}

export function rulesetLabel(ruleset: string): string {
  return ruleset.toUpperCase()
}

/** The groups in ruleset order, most severe detection first, optionally only the wanted detections. */
export function displayedGroups(groups: DetectionGroup[], wantedIds?: string[]): DetectionGroup[] {
  return groups
    .map((group) => ({
      ruleset: group.ruleset,
      detections: group.detections
        .filter((detection) => wantedIds === undefined || wantedIds.includes(detection.id))
        .sort((a, b) => compareSeverity(b.severity, a.severity)),
    }))
    .filter((group) => group.detections.length > 0)
    .sort((a, b) => rulesetRank(a.ruleset) - rulesetRank(b.ruleset))
}

export function detectionById(groups: DetectionGroup[], id: string): Detection | undefined {
  return groups.flatMap((group) => group.detections).find((detection) => detection.id === id)
}
