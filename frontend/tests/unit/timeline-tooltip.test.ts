import { describe, expect, it } from 'vitest'
import { tooltipAnchor, tooltipFor } from '@/services/timeline-tooltip'
import type { Hit } from '@/services/timeline-hit-test'
import { eventFixture } from './events-fixtures'

const mark = (overrides: Parameters<typeof eventFixture>[0]): Hit => {
  const event = eventFixture(overrides)
  return { kind: 'mark', mark: { kind: 'event', id: event.id, x: 0, y: 0, lane: event.lane ?? 'api', time: Date.parse(event.time), event } }
}

describe('the tooltip of an event mark', () => {
  it('shows the summary, the time, the process and its lane', () => {
    const tip = tooltipFor(mark({ id: 'a', time: '2026-10-13T15:39:50.123Z', summary: 'cmd.exe started powershell.exe' }))!
    expect(tip.title).toBe('cmd.exe started powershell.exe')
    expect(tip.lane).toBe('process')
    expect(tip.rows).toContainEqual({ label: 'TIME', value: '15:39:50.123' })
    expect(tip.rows).toContainEqual({ label: 'PROCESS', value: 'cmd.exe (2476)' })
  })

  it('falls back to the action and then the id when there is no summary', () => {
    expect(tooltipFor(mark({ id: 'a', summary: null, action: 'file-written' }))!.title).toBe('file-written')
    expect(tooltipFor(mark({ id: 'a', summary: null, action: null }))!.title).toBe('a')
  })

  it('leaves out the process of an event without one', () => {
    const tip = tooltipFor(mark({ id: 'a', process: null }))!
    expect(tip.rows.map((row) => row.label)).not.toContain('PROCESS')
  })

  it('names a process without a name by its pid alone', () => {
    const tip = tooltipFor(mark({ id: 'a', process: { pid: 7, name: null, entity_id: null } }))!
    expect(tip.rows).toContainEqual({ label: 'PROCESS', value: '(7)' })
  })

  it('adds at most three key fields, the informative ones first', () => {
    const tip = tooltipFor(
      mark({
        id: 'a',
        api_name: 'NtWriteFile',
        file_path: 'C:\\a.txt',
        registry_path: 'HKLM\\Run',
        url: 'http://x.test/',
        dns_query: 'x.test',
        destination: { ip: '10.0.0.1', port: 443, domain: 'x.test' },
        action: 'file-written',
      }),
    )!
    const keyRows = tip.rows.filter((row) => !['TIME', 'PROCESS'].includes(row.label))
    expect(keyRows).toEqual([
      { label: 'API', value: 'NtWriteFile' },
      { label: 'FILE', value: 'C:\\a.txt' },
      { label: 'KEY', value: 'HKLM\\Run' },
    ])
  })

  it('shows a destination as address, port and domain', () => {
    const tip = tooltipFor(mark({ id: 'a', lane: 'network', destination: { ip: '10.0.0.1', port: 443, domain: 'evil.example' } }))!
    expect(tip.rows).toContainEqual({ label: 'DEST', value: '10.0.0.1:443 (evil.example)' })
  })

  it('shows the severity of an alert event', () => {
    expect(tooltipFor(mark({ id: 'a', severity: 'high' }))!.severity).toBe('high')
  })

  it('says a click opens it', () => {
    expect(tooltipFor(mark({ id: 'a' }))!.hint).toBe('click to open')
  })
})

describe('the tooltip of a count mark', () => {
  const events = Array.from({ length: 5 }, (_, index) =>
    eventFixture({ id: `e${index}`, time: new Date(Date.UTC(2026, 9, 13, 15, 39, 50, 100 + index)).toISOString(), summary: `event ${index}`, lane: 'file' }),
  )
  const cluster = (start: number, end: number): Hit => ({
    kind: 'cluster',
    mark: { kind: 'cluster', x: 0, y: 0, lane: 'file', count: events.length, ids: events.map((e) => e.id), start, end, events },
  })

  it('counts the events, gives the time span and lists the first three', () => {
    const start = Date.UTC(2026, 9, 13, 15, 39, 50, 100)
    const tip = tooltipFor(cluster(start, start + 4))!
    expect(tip.title).toBe('5 FILE events')
    expect(tip.rows[0]).toEqual({ label: 'TIME', value: '15:39:50.100 - 15:39:50.104' })
    expect(tip.rows.slice(1).map((row) => row.value)).toEqual(['event 0', 'event 1', 'event 2', '+2 more'])
    expect(tip.hint).toBe('click to zoom in')
  })

  it('shows one instant once, and says a click opens the first event, when zooming cannot separate them', () => {
    const start = Date.UTC(2026, 9, 13, 15, 39, 50, 100)
    const tip = tooltipFor(cluster(start, start))!
    expect(tip.rows[0]).toEqual({ label: 'TIME', value: '15:39:50.100' })
    expect(tip.hint).toBe('click to open the first')
  })
})

describe('the tooltip of a bar', () => {
  const bar = (count: number): Hit => ({
    kind: 'bar',
    bar: { lane: 'registry', start: Date.UTC(2026, 9, 13, 15, 39, 50, 0), end: Date.UTC(2026, 9, 13, 15, 39, 52, 0), count, x: 0, width: 5, y: 0, height: 5, label: null },
  })

  it('gives the count, the lane, the time span and its length', () => {
    const tip = tooltipFor(bar(1234))!
    expect(tip.title).toBe('1,234 REGISTRY events')
    expect(tip.lane).toBe('registry')
    expect(tip.rows).toEqual([
      { label: 'TIME', value: '15:39:50.000 - 15:39:52.000' },
      { label: 'SPAN', value: '2.00 s' },
    ])
    expect(tip.hint).toBe('click to zoom in')
  })

  it('uses the singular for one event', () => {
    expect(tooltipFor(bar(1))!.title).toBe('1 REGISTRY event')
  })
})

describe('the tooltip of a detection', () => {
  const detection = (severity: 'high' | 'info'): Hit => ({
    kind: 'detection',
    detection: { id: 'd', x: 0, y: 0, time: Date.UTC(2026, 9, 13, 15, 40, 39, 668), name: 'injection_createremotethread', severity, ruleset: 'cape' },
  })

  it('gives the rule, its severity, ruleset and time', () => {
    const tip = tooltipFor(detection('high'))!
    expect(tip.title).toBe('injection_createremotethread')
    expect(tip.severity).toBe('high')
    expect(tip.lane).toBeNull()
    expect(tip.rows).toEqual([
      { label: 'RULESET', value: 'cape' },
      { label: 'TIME', value: '15:40:39.668' },
    ])
    expect(tip.hint).toBe('click to open')
  })

  it('has a title for a detection without a name', () => {
    const hit = detection('info')
    if (hit.kind === 'detection') hit.detection.name = null
    expect(tooltipFor(hit)!.title).toBe('detection')
  })

  it('leaves out the ruleset when there is none', () => {
    const hit = detection('high')
    if (hit.kind === 'detection') hit.detection.ruleset = null
    expect(tooltipFor(hit)!.rows.map((row) => row.label)).toEqual(['TIME'])
  })
})

describe('what has no tooltip', () => {
  it.each<Hit>([{ kind: 'plot' }, { kind: 'axis' }, { kind: 'gutter' }, { kind: 'handle', handle: 'start' }])('%j', (hit) => {
    expect(tooltipFor(hit)).toBeNull()
  })
})

describe('where the tooltip goes', () => {
  it('opens right and down from the pointer by default', () => {
    expect(tooltipAnchor({ x: 100, y: 50 }, { width: 1000, height: 260 })).toEqual({ horizontal: 'left', vertical: 'top' })
  })

  it('flips to the left of the pointer past the middle of the canvas', () => {
    expect(tooltipAnchor({ x: 600, y: 50 }, { width: 1000, height: 260 }).horizontal).toBe('right')
  })

  it('flips above the pointer in the lower part of the canvas', () => {
    expect(tooltipAnchor({ x: 100, y: 200 }, { width: 1000, height: 260 }).vertical).toBe('bottom')
  })
})
