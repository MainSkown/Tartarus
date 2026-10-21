import { describe, expect, it } from 'vitest'
import { clockDuration, elapsedSecondsAt } from '@/services/queue-view'
import type { RunningAnalysis } from '@/api'

const STARTED = '2026-10-21T10:00:00Z'
const STARTED_MS = Date.parse(STARTED)

function running(overrides: Partial<RunningAnalysis> = {}): RunningAnalysis {
  return { id: 42, filename: 'invoice.exe', guest: 'lab1', status: 'running', started_at: STARTED, elapsed_s: 0, ...overrides }
}

describe('clockDuration', () => {
  it.each([
    [0, '00:00'],
    [72, '01:12'],
    [3599, '59:59'],
    [3600, '1:00:00'],
    [3725, '1:02:05'],
  ])('shows %i seconds as %s', (seconds, expected) => {
    expect(clockDuration(seconds)).toBe(expected)
  })
})

describe('elapsedSecondsAt', () => {
  it('counts on from started_at so the clock keeps moving between pushes', () => {
    expect(elapsedSecondsAt(running(), STARTED_MS + 72_400)).toBe(72)
  })

  it('falls back to the server figure when started_at is missing', () => {
    expect(elapsedSecondsAt(running({ started_at: null, elapsed_s: 5 }), STARTED_MS)).toBe(5)
  })

  it('never goes below zero when the clock is behind started_at', () => {
    expect(elapsedSecondsAt(running(), STARTED_MS - 5_000)).toBe(0)
  })
})
