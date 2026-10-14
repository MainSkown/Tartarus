import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref, type EffectScope } from 'vue'
import { eventDetail, eventFixture } from './events-fixtures'

const eventsDetailMock = vi.fn()
vi.mock('@/api', () => ({ eventsDetail: (...args: unknown[]) => eventsDetailMock(...args) }))

const { useEventDetail } = await import('@/composables/use-event-detail')

const analysisId = ref<number | undefined>(7)
const eventId = ref<string | null>(null)

function ok(id: string) {
  return { data: eventDetail(eventFixture({ id })), error: undefined, response: { status: 200 } }
}

function failed(status: number, message: string) {
  return { data: undefined, error: { error: { code: 'x', message, details: {} } }, response: { status } }
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

const scopes: EffectScope[] = []

function track() {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => useEventDetail(() => analysisId.value, () => eventId.value))!
}

afterEach(() => scopes.splice(0).forEach((scope) => scope.stop()))

beforeEach(() => {
  eventsDetailMock.mockReset()
  eventsDetailMock.mockImplementation(async ({ path }: { path: { event_id: string } }) => ok(path.event_id))
  analysisId.value = 7
  eventId.value = null
})

describe('useEventDetail', () => {
  it('asks for nothing while no event is open', async () => {
    const detail = track()
    await flushPromises()
    expect(eventsDetailMock).not.toHaveBeenCalled()
    expect(detail.detail.value).toBeUndefined()
    expect(detail.loading.value).toBe(false)
  })

  it('loads the event that is opened, by analysis and id', async () => {
    eventId.value = 'abc:1/2'
    const detail = track()
    expect(detail.loading.value).toBe(true)
    await flushPromises()
    expect(eventsDetailMock.mock.calls[0]![0].path).toEqual({ analysis_id: 7, event_id: 'abc:1/2' })
    expect(detail.detail.value?.event.id).toBe('abc:1/2')
    expect(detail.loading.value).toBe(false)
  })

  it('loads the next event when the open one changes, keeping the old one on show until then', async () => {
    eventId.value = 'a'
    const detail = track()
    await flushPromises()
    const pending = deferred<unknown>()
    eventsDetailMock.mockReturnValueOnce(pending.promise)
    eventId.value = 'b'
    await nextTick()
    expect(detail.loading.value).toBe(true)
    expect(detail.detail.value?.event.id).toBe('a')
    pending.resolve(ok('b'))
    await flushPromises()
    expect(detail.detail.value?.event.id).toBe('b')
  })

  it('drops the answer for an event that is no longer the open one', async () => {
    eventId.value = 'slow'
    const slow = deferred<unknown>()
    eventsDetailMock.mockReturnValueOnce(slow.promise)
    const detail = track()
    eventId.value = 'fast'
    await flushPromises()
    slow.resolve(ok('slow'))
    await flushPromises()
    expect(detail.detail.value?.event.id).toBe('fast')
  })

  it('forgets the event when it is closed, and ignores an answer still on its way', async () => {
    eventId.value = 'slow'
    const slow = deferred<unknown>()
    eventsDetailMock.mockReturnValueOnce(slow.promise)
    const detail = track()
    eventId.value = null
    await flushPromises()
    slow.resolve(ok('slow'))
    await flushPromises()
    expect(detail.detail.value).toBeUndefined()
    expect(detail.loading.value).toBe(false)
  })

  it('tells a missing event from a failed request', async () => {
    eventsDetailMock.mockResolvedValueOnce(failed(404, 'event not found'))
    eventId.value = 'gone'
    const detail = track()
    await flushPromises()
    expect(detail.notFound.value).toBe(true)
    expect(detail.detail.value).toBeUndefined()

    eventsDetailMock.mockResolvedValueOnce(failed(502, 'search failed'))
    eventId.value = 'broken'
    await flushPromises()
    expect(detail.notFound.value).toBe(false)
    expect(detail.error.value).toBe('search failed')
  })

  it('retries the same event', async () => {
    eventsDetailMock.mockResolvedValueOnce(failed(504, 'the search took too long'))
    eventId.value = 'a'
    const detail = track()
    await flushPromises()
    await detail.reload()
    expect(detail.error.value).toBeUndefined()
    expect(detail.detail.value?.event.id).toBe('a')
  })

  it('does not keep the old event on show after a failure for the next', async () => {
    eventId.value = 'a'
    const detail = track()
    await flushPromises()
    eventsDetailMock.mockResolvedValueOnce(failed(404, 'gone'))
    eventId.value = 'b'
    await flushPromises()
    expect(detail.detail.value).toBeUndefined()
  })
})
