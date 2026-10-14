import { describe, expect, it } from 'vitest'
import { MAX_LIVE_DETECTIONS, collectDetections, liveDetectionOf } from '@/services/live-detections'
import { liveEvent, sigmaAlert } from './live-fixtures'

describe('liveDetectionOf', () => {
  it('reads a Sigma alert: rule name, ruleset, severity, techniques, process and time', () => {
    expect(liveDetectionOf(sigmaAlert({ id: 'a1', severity: 4 }))).toEqual({
      id: 'a1',
      name: 'Tartarus Self-Test Registry Marker Written',
      ruleset: 'sigma',
      severity: 'critical',
      techniques: ['T1112'],
      time: '2026-10-13T15:39:51.100Z',
      process: { pid: 9708, name: 'benign.exe' },
    })
  })

  it.each([
    [0, 'info'],
    [1, 'low'],
    [2, 'medium'],
    [3, 'high'],
    [4, 'critical'],
  ])('maps the event severity %i to %s', (severity, name) => {
    expect(liveDetectionOf(sigmaAlert({ severity }))?.severity).toBe(name)
  })

  it('is not made of an event that is not an alert', () => {
    expect(liveDetectionOf(liveEvent())).toBeUndefined()
  })

  it('falls back to the summary when the rule has no name, and to no techniques or process', () => {
    const alert = sigmaAlert()
    delete (alert as Partial<typeof alert>).rule
    delete (alert as Partial<typeof alert>).threat
    delete (alert as Partial<typeof alert>).process
    expect(liveDetectionOf(alert)).toMatchObject({
      name: 'Tartarus Self-Test Registry Marker Written',
      ruleset: 'unknown',
      techniques: [],
      process: null,
    })
  })

  it('treats a severity it does not know as info rather than failing', () => {
    expect(liveDetectionOf(sigmaAlert({ severity: 99 }))?.severity).toBe('info')
  })
})

describe('collectDetections', () => {
  it('appends the alerts of a batch and ignores its other events', () => {
    const result = collectDetections([], [liveEvent({ id: 'e1' }), sigmaAlert({ id: 'a1' }), liveEvent({ id: 'e2' })])
    expect(result.map((detection) => detection.id)).toEqual(['a1'])
  })

  it('returns the very same list when the batch holds no alert', () => {
    const known = collectDetections([], [sigmaAlert({ id: 'a1' })])
    expect(collectDetections(known, [liveEvent()])).toBe(known)
  })

  it('keeps an alert once however often it is sent', () => {
    const known = collectDetections([], [sigmaAlert({ id: 'a1' })])
    expect(collectDetections(known, [sigmaAlert({ id: 'a1' })])).toHaveLength(1)
  })

  it('keeps the newest alerts when there are more than the limit', () => {
    const batch = Array.from({ length: MAX_LIVE_DETECTIONS + 5 }, (_, index) => sigmaAlert({ id: `a${index}` }))
    const result = collectDetections([], batch)
    expect(result).toHaveLength(MAX_LIVE_DETECTIONS)
    expect(result[0]!.id).toBe('a5')
  })
})
