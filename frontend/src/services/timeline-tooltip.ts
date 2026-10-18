import type { Event, Severity } from '@/api'
import { t } from '@/i18n'
import { eventProcess, eventTitle } from '@/services/event-display'
import { formatCount } from '@/services/format-number'
import { formatClockTime } from '@/services/format-time'
import { laneMeta } from '@/services/lanes'
import type { Hit } from '@/services/timeline-hit-test'
import { formatSpanLength } from '@/services/timeline-axis'

export interface TooltipRow {
  label: string
  value: string
}

export interface Tooltip {
  /** The lane whose icon goes in front of the title; null for a detection, which is not a lane. */
  lane: string | null
  severity: Severity | null
  title: string
  rows: TooltipRow[]
  /** What a click does, in words. */
  hint: string
}

const MAX_KEY_FIELDS = 3
const MAX_LISTED_EVENTS = 3

const clock = (time: number): string => formatClockTime(new Date(time).toISOString())

function timeRows(start: number, end: number): TooltipRow[] {
  const value = start === end ? clock(start) : t('timeline.tooltip.timeRange', { start: clock(start), end: clock(end) })
  return [{ label: t('timeline.tooltip.row.time'), value }]
}

function destinationText(event: Event): string {
  const address = [event.destination?.ip, event.destination?.port].filter((part) => part !== null && part !== undefined).join(':')
  const domain = event.destination?.domain
  if (!domain) return address
  return address ? t('timeline.tooltip.destination', { address, domain }) : domain
}

function keyFields(event: Event): TooltipRow[] {
  const candidates: TooltipRow[] = [
    { label: t('timeline.tooltip.row.api'), value: event.api_name ?? '' },
    { label: t('timeline.tooltip.row.file'), value: event.file_path ?? '' },
    { label: t('timeline.tooltip.row.key'), value: event.registry_path ?? '' },
    { label: t('timeline.tooltip.row.url'), value: event.url ?? '' },
    { label: t('timeline.tooltip.row.dns'), value: event.dns_query ?? '' },
    { label: t('timeline.tooltip.row.dest'), value: destinationText(event) },
    { label: t('timeline.tooltip.row.action'), value: event.action ?? '' },
  ]
  return candidates.filter((row) => row.value !== '').slice(0, MAX_KEY_FIELDS)
}

function processRow(event: Event): TooltipRow[] {
  const process = eventProcess(event)
  return process ? [{ label: t('timeline.tooltip.row.process'), value: [process.name, t('timeline.tooltip.pid', { pid: process.pid })].filter(Boolean).join(' ') }] : []
}

function eventTooltip(event: Event, lane: string): Tooltip {
  return {
    lane,
    severity: event.severity,
    title: eventTitle(event),
    rows: [...timeRows(Date.parse(event.time), Date.parse(event.time)), ...processRow(event), ...keyFields(event)],
    hint: t('timeline.tooltip.hint.open'),
  }
}

function eventsTitle(count: number, lane: string): string {
  return t('timeline.tooltip.events', { count: formatCount(count), lane: laneMeta(lane).label }, count)
}

/** What the tooltip over a hit says; null for the parts of the canvas that have none. */
export function tooltipFor(hit: Hit): Tooltip | null {
  switch (hit.kind) {
    case 'mark':
      return eventTooltip(hit.mark.event, hit.mark.lane)
    case 'cluster': {
      const { mark } = hit
      const listed = mark.events.slice(0, MAX_LISTED_EVENTS).map((event) => ({ label: formatClockTime(event.time), value: eventTitle(event) }))
      const more = mark.count > MAX_LISTED_EVENTS ? [{ label: '', value: t('timeline.tooltip.more', { count: mark.count - MAX_LISTED_EVENTS }) }] : []
      return {
        lane: mark.lane,
        severity: null,
        title: eventsTitle(mark.count, mark.lane),
        rows: [...timeRows(mark.start, mark.end), ...listed, ...more],
        hint: mark.start < mark.end ? t('timeline.tooltip.hint.zoomIn') : t('timeline.tooltip.hint.openFirst'),
      }
    }
    case 'bar':
      return {
        lane: hit.bar.lane,
        severity: null,
        title: eventsTitle(hit.bar.count, hit.bar.lane),
        rows: [...timeRows(hit.bar.start, hit.bar.end), { label: t('timeline.tooltip.row.span'), value: formatSpanLength(hit.bar.end - hit.bar.start) }],
        hint: t('timeline.tooltip.hint.zoomIn'),
      }
    case 'detection': {
      const { detection } = hit
      return {
        lane: null,
        severity: detection.severity,
        title: detection.name ?? t('timeline.tooltip.detection'),
        rows: [...(detection.ruleset ? [{ label: t('timeline.tooltip.row.ruleset'), value: detection.ruleset }] : []), ...timeRows(detection.time, detection.time)],
        hint: t('timeline.tooltip.hint.open'),
      }
    }
    default:
      return null
  }
}

export interface TooltipAnchor {
  horizontal: 'left' | 'right'
  vertical: 'top' | 'bottom'
}

/** Which corner of the tooltip sits at the pointer: it opens toward the middle of the canvas so it stays on it. */
export function tooltipAnchor(pointer: { x: number; y: number }, canvas: { width: number; height: number }): TooltipAnchor {
  return {
    horizontal: pointer.x > canvas.width / 2 ? 'right' : 'left',
    vertical: pointer.y > canvas.height * 0.6 ? 'bottom' : 'top',
  }
}
