import type { QueryTimeRange } from '@/services/query-url'
import { NO_EVENTS, type RangeOverride } from '@/services/range-override'
import { queryRangeToSpan, spanToQueryRange } from '@/services/timeline-brush'
import { activePreset, intersect, type Span } from '@/services/timeline-scale'

/**
 * What the events table under the timeline is restricted to: the visible range where it is narrower
 * than the whole analysis, cut down to the time-range chip when there is one. At the fit view the
 * shared chip alone applies, so there is nothing to override (null).
 */
export function tableRangeFor(view: Span | null, full: Span | null, chip: QueryTimeRange | null): RangeOverride | null {
  if (view === null || full === null || activePreset(view, full) === 'fit') return null
  const chipSpan = chip === null ? null : queryRangeToSpan(chip, full)
  const restricted = chipSpan === null ? view : intersect(view, chipSpan)
  return restricted === null ? NO_EVENTS : spanToQueryRange(restricted)
}
