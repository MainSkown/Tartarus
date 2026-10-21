import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { useActivityAge } from '@/composables/use-activity-age'

const NOW = new Date('2026-10-21T12:10:00Z')

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => vi.useRealTimers())

function followed(initial: string | null | undefined) {
  const lastActivity = ref(initial)
  const scope = effectScope()
  const notice = scope.run(() => useActivityAge(() => lastActivity.value))!
  return { lastActivity, notice, scope }
}

describe('useActivityAge', () => {
  it('shows nothing before the build has shown any activity', () => {
    expect(followed(null).notice.value).toBeUndefined()
  })

  it('starts from the age of the last activity', () => {
    expect(followed('2026-10-21T12:09:55Z').notice.value?.text).toBe('last activity 5s ago')
  })

  it('counts on each second by itself, without a new answer from the server', async () => {
    const { notice } = followed('2026-10-21T12:09:55Z')
    await vi.advanceTimersByTimeAsync(1_000)
    expect(notice.value?.text).toBe('last activity 6s ago')
    await vi.advanceTimersByTimeAsync(4_000)
    expect(notice.value?.text).toBe('last activity 10s ago')
  })

  it('turns stale after two minutes of silence and recovers when something new arrives', async () => {
    const { notice, lastActivity } = followed('2026-10-21T12:09:00Z')
    expect(notice.value?.stale).toBe(false)
    await vi.advanceTimersByTimeAsync(61_000)
    expect(notice.value).toEqual({ text: 'no news for 2 min: the step may be waiting or stuck', stale: true })
    lastActivity.value = new Date(Date.now() - 1_000).toISOString()
    await nextTick()
    expect(notice.value).toEqual({ text: 'last activity 1s ago', stale: false })
  })

  it('stops ticking when its scope ends', async () => {
    const { scope } = followed('2026-10-21T12:09:55Z')
    expect(vi.getTimerCount()).toBe(1)
    scope.stop()
    expect(vi.getTimerCount()).toBe(0)
  })
})
