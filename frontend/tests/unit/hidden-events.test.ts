import { describe, expect, it } from 'vitest'
import { hiddenEventBreakdown, hiddenEventsTotal } from '@/services/hidden-events'

describe('hidden events', () => {
  const counts = { 'windows-background': 410, 'cape-tooling': 12, 'monitor-artefact': 0, 'sysmon-service': 3, 'unmapped-event': 5 }

  it('totals every hidden event, since the backend counts them all as left out', () => {
    expect(hiddenEventsTotal(counts)).toBe(430)
  })

  it('totals nothing for no counts', () => {
    expect(hiddenEventsTotal(undefined)).toBe(0)
    expect(hiddenEventsTotal({})).toBe(0)
  })

  it('breaks the total down by reason, largest first, leaving out zero counts', () => {
    expect(hiddenEventBreakdown(counts)).toEqual([
      { label: 'Windows background', count: 410 },
      { label: "The sandbox's own tools", count: 12 },
      { label: 'Events Tartarus does not map', count: 5 },
      { label: "Sysmon's own service", count: 3 },
    ])
  })

  it('shows a reason the catalogue does not know as it came', () => {
    expect(hiddenEventBreakdown({ 'new-reason': 2 })).toEqual([{ label: 'new-reason', count: 2 }])
  })
})
