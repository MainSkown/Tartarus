import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import type { QueryErrorRead } from '@/api'

const queryValidateMock = vi.fn()
vi.mock('@/api', () => ({ queryValidate: (...args: unknown[]) => queryValidateMock(...args) }))

const { useQueryValidation, VALIDATION_DELAY_MS } = await import('@/composables/use-query-validation')

const UNKNOWN_FIELD: QueryErrorRead = { start: 0, end: 5, message: "unknown field 'prcss'", suggestion: 'process' }

function validation(initial = '') {
  const draft = ref(initial)
  const scope = effectScope()
  const result = scope.run(() => useQueryValidation(draft))!
  return { draft, result, stop: () => scope.stop() }
}

function answer(errors: QueryErrorRead[]) {
  return { data: { ok: errors.length === 0, errors }, error: undefined }
}

beforeEach(() => {
  vi.useFakeTimers()
  queryValidateMock.mockReset()
  queryValidateMock.mockResolvedValue(answer([]))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useQueryValidation', () => {
  it('waits for a pause in typing before asking', async () => {
    const { draft } = validation()
    draft.value = 'prcss:x'
    await nextTick()
    vi.advanceTimersByTime(VALIDATION_DELAY_MS - 1)
    expect(queryValidateMock).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(queryValidateMock).toHaveBeenCalledWith(expect.objectContaining({ body: { query: 'prcss:x' } }))
  })

  it('asks only about the last text of a burst of typing', async () => {
    const { draft } = validation()
    for (const text of ['p', 'pr', 'prc']) {
      draft.value = text
      await nextTick()
      vi.advanceTimersByTime(100)
    }
    vi.advanceTimersByTime(VALIDATION_DELAY_MS)
    expect(queryValidateMock).toHaveBeenCalledTimes(1)
    expect(queryValidateMock.mock.calls[0]![0].body.query).toBe('prc')
  })

  it('validates a draft that is already filled when it starts, as a query opened from a link is', async () => {
    queryValidateMock.mockResolvedValue(answer([UNKNOWN_FIELD]))
    const { result } = validation('prcss:x')
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    expect(result.errors.value).toEqual([UNKNOWN_FIELD])
  })

  it('exposes the errors of the answer', async () => {
    queryValidateMock.mockResolvedValue(answer([UNKNOWN_FIELD]))
    const { draft, result } = validation()
    draft.value = 'prcss:x'
    await nextTick()
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    expect(result.errors.value).toEqual([UNKNOWN_FIELD])
  })

  it('does not ask about an empty or blank draft, and clears the errors at once', async () => {
    queryValidateMock.mockResolvedValue(answer([UNKNOWN_FIELD]))
    const { draft, result } = validation()
    draft.value = 'prcss:x'
    await nextTick()
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    queryValidateMock.mockClear()

    draft.value = '  '
    await nextTick()
    expect(result.errors.value).toEqual([])
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    expect(queryValidateMock).not.toHaveBeenCalled()
  })

  it('shows no error and does not block when the request fails', async () => {
    queryValidateMock.mockResolvedValue({ data: undefined, error: { error: { message: 'down' } } })
    const { draft, result } = validation()
    draft.value = 'x'
    await nextTick()
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    expect(result.errors.value).toEqual([])
    expect(await result.settle()).toEqual([])
  })

  it('shows no error when the request throws', async () => {
    queryValidateMock.mockRejectedValue(new TypeError('Failed to fetch'))
    const { draft, result } = validation()
    draft.value = 'x'
    await nextTick()
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    expect(result.errors.value).toEqual([])
  })

  it('drops the answer of a text that is no longer the draft', async () => {
    let resolveFirst: (value: unknown) => void = () => undefined
    queryValidateMock.mockReturnValueOnce(new Promise((resolve) => (resolveFirst = resolve)))
    const { draft, result } = validation()
    draft.value = 'first'
    await nextTick()
    vi.advanceTimersByTime(VALIDATION_DELAY_MS)

    draft.value = 'second'
    await nextTick()
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    resolveFirst(answer([UNKNOWN_FIELD]))
    await flushPromises()
    expect(result.errors.value).toEqual([])
  })

  it('settles by asking right away for a draft whose answer is still pending', async () => {
    queryValidateMock.mockResolvedValue(answer([UNKNOWN_FIELD]))
    const { draft, result } = validation()
    draft.value = 'prcss:x'
    await nextTick()
    const errors = await result.settle()
    expect(errors).toEqual([UNKNOWN_FIELD])
    expect(queryValidateMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    expect(queryValidateMock).toHaveBeenCalledTimes(1)
  })

  it('settles without asking again when the answer is already in', async () => {
    const { draft, result } = validation()
    draft.value = 'x'
    await nextTick()
    await vi.advanceTimersByTimeAsync(VALIDATION_DELAY_MS)
    await result.settle()
    expect(queryValidateMock).toHaveBeenCalledTimes(1)
  })

  it('settles a blank draft as no errors without asking', async () => {
    const { result } = validation('')
    expect(await result.settle()).toEqual([])
    expect(queryValidateMock).not.toHaveBeenCalled()
  })
})
