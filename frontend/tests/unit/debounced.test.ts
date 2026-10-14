import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { debounced } from '@/services/debounced'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('debounced', () => {
  it('runs once, after the quiet period, for a burst of calls', () => {
    const run = vi.fn()
    const call = debounced(run, 50)
    call()
    vi.advanceTimersByTime(30)
    call()
    vi.advanceTimersByTime(30)
    expect(run).not.toHaveBeenCalled()
    vi.advanceTimersByTime(20)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('can be cancelled', () => {
    const run = vi.fn()
    const call = debounced(run, 50)
    call()
    call.cancel()
    vi.advanceTimersByTime(100)
    expect(run).not.toHaveBeenCalled()
  })

  it('runs immediately on flush, and not again afterwards', () => {
    const run = vi.fn()
    const call = debounced(run, 50)
    call()
    call.flush()
    vi.advanceTimersByTime(100)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('does nothing on flush when nothing is waiting', () => {
    const run = vi.fn()
    debounced(run, 50).flush()
    expect(run).not.toHaveBeenCalled()
  })
})
