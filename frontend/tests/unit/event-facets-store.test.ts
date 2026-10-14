import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { facetFixture, facetsResponse } from './events-fixtures'

const eventsFacetsMock = vi.fn()
vi.mock('@/api', () => ({ eventsFacets: (...args: unknown[]) => eventsFacetsMock(...args) }))

const { useEventFacetsStore, FACETS_DEBOUNCE_MS } = await import('@/stores/event-facets')
const { useEventsStore } = await import('@/stores/events')
const { useQueryStateStore } = await import('@/stores/query-state')
const { FACET_FIELDS } = await import('@/services/event-fields')

let facets: ReturnType<typeof useEventFacetsStore>
let query: ReturnType<typeof useQueryStateStore>

const PROCESS_FACET = facetFixture('process.name', [
  ['cmd.exe', 40],
  ['svchost.exe', 12],
])

function ok(...found: ReturnType<typeof facetFixture>[]) {
  return { data: facetsResponse(found), error: undefined, response: { status: 200 } }
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

async function settle() {
  await vi.advanceTimersByTimeAsync(0)
}

async function afterDebounce() {
  await vi.advanceTimersByTimeAsync(FACETS_DEBOUNCE_MS + 1)
}

function lastRequest() {
  return eventsFacetsMock.mock.lastCall![0] as { path: { analysis_id: number }; body: Record<string, unknown> }
}

async function startOn(analysisId = 7) {
  query.bindTo(analysisId)
  facets.activate()
  await settle()
}

beforeEach(() => {
  vi.useFakeTimers()
  eventsFacetsMock.mockReset()
  eventsFacetsMock.mockResolvedValue(ok(PROCESS_FACET))
  setActivePinia(createPinia())
  query = useQueryStateStore()
  facets = useEventFacetsStore()
})

afterEach(() => vi.useRealTimers())

describe('asking', () => {
  it('asks for the six default facets with the current filter', async () => {
    query.bindTo(7)
    query.setText('lane:file')
    query.addChip({ field: 'process.name', value: 'cmd.exe', negate: true })
    facets.activate()
    await settle()
    expect(lastRequest().path).toEqual({ analysis_id: 7 })
    expect(lastRequest().body).toEqual({
      query: 'lane:file',
      filters: [{ field: 'process.name', value: 'cmd.exe', negate: true }],
      fields: FACET_FIELDS,
    })
    expect(FACET_FIELDS).toEqual(['process.name', 'tartarus.lane', 'event.action', 'api.name', 'destination.domain', 'rule.name'])
  })

  it('does not ask while no analysis is bound', async () => {
    facets.activate()
    await settle()
    expect(eventsFacetsMock).not.toHaveBeenCalled()
  })

  it('finds a facet by the field it was asked for', async () => {
    await startOn()
    expect(facets.byField('process.name')).toEqual(PROCESS_FACET)
    expect(facets.byField('rule.name')).toBeUndefined()
  })

  it('is loading until the answer arrives', async () => {
    const pending = deferred<unknown>()
    eventsFacetsMock.mockReturnValue(pending.promise)
    await startOn()
    expect(facets.loading).toBe(true)
    pending.resolve(ok(PROCESS_FACET))
    await settle()
    expect(facets.loading).toBe(false)
  })
})

describe('refetching', () => {
  it('asks again, once, when the filter changes', async () => {
    await startOn()
    query.setText('a')
    query.setText('ab')
    await afterDebounce()
    expect(eventsFacetsMock).toHaveBeenCalledTimes(2)
    expect(lastRequest().body).toMatchObject({ query: 'ab' })
  })

  it('does not ask again when only the sort changes', async () => {
    const events = useEventsStore()
    await startOn()
    events.toggleSort()
    await afterDebounce()
    expect(eventsFacetsMock).toHaveBeenCalledTimes(1)
  })

  it('does not ask again when the open event changes', async () => {
    await startOn()
    query.openEvent('e1')
    await afterDebounce()
    expect(eventsFacetsMock).toHaveBeenCalledTimes(1)
  })

  it('drops the answer to an older filter that arrives late', async () => {
    await startOn()
    const slow = deferred<unknown>()
    eventsFacetsMock.mockReturnValueOnce(slow.promise)
    query.setText('slow')
    await afterDebounce()
    eventsFacetsMock.mockResolvedValueOnce(ok(facetFixture('process.name', [['new.exe', 1]])))
    query.setText('fast')
    await afterDebounce()
    slow.resolve(ok(PROCESS_FACET))
    await settle()
    expect(facets.byField('process.name')?.values[0]?.value).toBe('new.exe')
  })

  it('keeps the old counts, marked loading, while new ones are on their way', async () => {
    await startOn()
    eventsFacetsMock.mockReturnValueOnce(new Promise(() => undefined))
    query.setText('x')
    await afterDebounce()
    expect(facets.loading).toBe(true)
    expect(facets.byField('process.name')).toEqual(PROCESS_FACET)
  })

  it('forgets the counts of another analysis at once', async () => {
    await startOn(7)
    eventsFacetsMock.mockReturnValueOnce(new Promise(() => undefined))
    query.bindTo(8)
    await settle()
    expect(facets.byField('process.name')).toBeUndefined()
  })

  it('asks nothing while the tab is not shown, and asks on showing it if the filter changed', async () => {
    await startOn()
    facets.deactivate()
    query.setText('x')
    await afterDebounce()
    expect(eventsFacetsMock).toHaveBeenCalledTimes(1)
    facets.activate()
    await settle()
    expect(eventsFacetsMock).toHaveBeenCalledTimes(2)
  })
})

describe('failing', () => {
  it('reports the failure and offers a retry, without throwing', async () => {
    eventsFacetsMock.mockResolvedValueOnce({
      data: undefined,
      error: { error: { code: 'search_timeout', message: 'the search took too long', details: {} } },
      response: { status: 504 },
    })
    await startOn()
    expect(facets.error).toBe('the search took too long')
    expect(facets.byField('process.name')).toBeUndefined()
    expect(facets.loading).toBe(false)
    await facets.retry()
    expect(facets.error).toBeUndefined()
    expect(facets.byField('process.name')).toEqual(PROCESS_FACET)
  })
})
