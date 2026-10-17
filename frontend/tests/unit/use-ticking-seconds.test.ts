import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type EffectScope, type Ref } from 'vue'
import type { Reading } from '@/composables/use-ticking-seconds'

const { useTickingSeconds } = await import('@/composables/use-ticking-seconds')

const NOW = Date.parse('2026-10-13T15:40:00Z')

let scope: EffectScope
let reading: Ref<Reading | undefined>
let counting: Ref<boolean>

function start(direction: 1 | -1) {
  scope = effectScope()
  return scope.run(() => useTickingSeconds(() => reading.value, { direction, counting: () => counting.value }))!
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
  reading = ref<Reading | undefined>({ seconds: 108, receivedAt: NOW })
  counting = ref(true)
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
})

describe('useTickingSeconds', () => {
  it('counts down from the reading it was given', async () => {
    const seconds = start(-1)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(seconds.value).toBe(103)
  })

  it('counts up for a direction of 1', async () => {
    reading.value = { seconds: 72, receivedAt: NOW }
    const seconds = start(1)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(seconds.value).toBe(77)
  })

  it('does not go below zero', async () => {
    reading.value = { seconds: 2, receivedAt: NOW }
    const seconds = start(-1)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(seconds.value).toBe(0)
  })

  it('holds still while not counting', async () => {
    counting.value = false
    const seconds = start(-1)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(seconds.value).toBe(108)
  })

  it('jumps to the figure of a new reading, as when an extension raises the remaining time', async () => {
    const seconds = start(-1)
    await vi.advanceTimersByTimeAsync(5_000)
    reading.value = { seconds: 240, receivedAt: Date.now() }
    expect(seconds.value).toBe(240)
  })

  it('shows nothing when there is no reading', () => {
    reading.value = undefined
    expect(start(-1).value).toBeNull()
  })
})
