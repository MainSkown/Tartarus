import { describe, expect, it } from 'vitest'
import type { GuestState } from '@/api'
import { GUEST_STATES, guestStateMeta, isInProgress } from '@/services/guest-state'

describe('guestStateMeta', () => {
  it.each(GUEST_STATES)('gives %s a label, an icon and a colour token', (state) => {
    const meta = guestStateMeta(state)
    expect(meta.label).toBe(state.toUpperCase())
    expect(meta.icon).not.toBe('')
    expect(meta.color).toMatch(/^--/)
  })

  it('knows every state the API has', () => {
    expect([...GUEST_STATES].sort()).toEqual(['broken', 'building', 'failed', 'ready', 'testing'])
  })

  it('gives each state its own icon, so colour is never the only signal', () => {
    const icons = GUEST_STATES.map((state) => guestStateMeta(state).icon)
    expect(new Set(icons).size).toBe(icons.length)
  })

  it('shows a state a newer backend adds as itself, in a neutral look', () => {
    const meta = guestStateMeta('hibernating' as GuestState)
    expect(meta.label).toBe('HIBERNATING')
    expect(meta.color).toBe('--text-gray')
    expect(meta.active).toBe(false)
  })

  it('is red for failed and broken, green for ready', () => {
    expect(guestStateMeta('failed').color).toBe('--status-critical')
    expect(guestStateMeta('broken').color).toBe('--status-critical')
    expect(guestStateMeta('ready').color).toBe('--status-success')
  })
})

describe('isInProgress', () => {
  it.each([
    ['building', true],
    ['testing', true],
    ['ready', false],
    ['failed', false],
    ['broken', false],
  ] as const)('%s is %s', (state, expected) => {
    expect(isInProgress(state)).toBe(expected)
    expect(guestStateMeta(state).active).toBe(expected)
  })
})
