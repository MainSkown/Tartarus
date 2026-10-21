import { createPinia, setActivePinia } from 'pinia'
import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CrossSearchResponse } from '@/api'
import { eventFixture } from './events-fixtures'

const searchAcrossAnalysesMock = vi.fn()
vi.mock('@/api', () => ({
  searchAcrossAnalyses: (...args: unknown[]) => searchAcrossAnalysesMock(...args),
}))

const { useCrossSearch, CROSS_SEARCH_PAGE_SIZE } = await import('@/composables/use-cross-search')

const FILTER = { query: 'process.name:cmd.exe' }

function page(hits: Array<{ analysis_id: number; id: string }>, overrides: Partial<CrossSearchResponse> = {}): CrossSearchResponse {
  return {
    events: hits.map(({ analysis_id, id }) => ({ analysis_id, event: eventFixture({ id }) })),
    total: hits.length,
    next_cursor: null,
    ...overrides,
  }
}

function answer(body: CrossSearchResponse) {
  return { data: body, error: undefined, response: { status: 200 } }
}

function failure(status: number, message: string) {
  return { data: undefined, error: { error: { code: 'boom', message } }, response: { status } }
}

function search() {
  const scope = effectScope()
  const result = scope.run(() => useCrossSearch())!
  return { ...result, stop: () => scope.stop() }
}

beforeEach(() => {
  setActivePinia(createPinia())
  searchAcrossAnalysesMock.mockReset()
})

afterEach(() => window.localStorage.clear())

describe('useCrossSearch', () => {
  it('asks nothing until a search is run', () => {
    const cross = search()
    expect(cross.searched.value).toBe(false)
    expect(searchAcrossAnalysesMock).not.toHaveBeenCalled()
    cross.stop()
  })

  it('sends the filter with one page size and keeps each row with its analysis id', async () => {
    searchAcrossAnalysesMock.mockResolvedValue(answer(page([{ analysis_id: 3, id: 'a' }, { analysis_id: 9, id: 'b' }])))
    const cross = search()
    await cross.run(FILTER)
    expect(searchAcrossAnalysesMock).toHaveBeenCalledWith(
      expect.objectContaining({ body: { ...FILTER, sort: '@timestamp', size: CROSS_SEARCH_PAGE_SIZE } }),
    )
    expect(cross.rows.value.map((row) => [row.id, row.analysis_id])).toEqual([
      ['a', 3],
      ['b', 9],
    ])
    expect(cross.total.value).toBe(2)
    expect(cross.searched.value).toBe(true)
    cross.stop()
  })

  it('follows the cursor for the next page and appends its rows', async () => {
    searchAcrossAnalysesMock
      .mockResolvedValueOnce(answer(page([{ analysis_id: 3, id: 'a' }], { next_cursor: 'cursor-1', total: 2 })))
      .mockResolvedValueOnce(answer(page([{ analysis_id: 4, id: 'b' }])))
    const cross = search()
    await cross.run(FILTER)
    expect(cross.hasMore.value).toBe(true)
    await cross.loadMore()
    expect(searchAcrossAnalysesMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ body: expect.objectContaining({ search_after: 'cursor-1' }) }),
    )
    expect(cross.rows.value.map((row) => row.id)).toEqual(['a', 'b'])
    expect(cross.hasMore.value).toBe(false)
    cross.stop()
  })

  it('reports a failed search with its message and no rows', async () => {
    searchAcrossAnalysesMock.mockResolvedValue(failure(502, 'opensearch is down'))
    const cross = search()
    await cross.run(FILTER)
    expect(cross.error.value?.message).toBe('opensearch is down')
    expect(cross.rows.value).toEqual([])
    cross.stop()
  })

  it('keeps the rows and names the failure when the next page fails', async () => {
    searchAcrossAnalysesMock
      .mockResolvedValueOnce(answer(page([{ analysis_id: 3, id: 'a' }], { next_cursor: 'cursor-1' })))
      .mockResolvedValueOnce(failure(504, 'timed out'))
    const cross = search()
    await cross.run(FILTER)
    await cross.loadMore()
    expect(cross.rows.value.map((row) => row.id)).toEqual(['a'])
    expect(cross.loadMoreError.value).toBe('timed out')
    cross.stop()
  })

  it('runs the last filter again on retry', async () => {
    searchAcrossAnalysesMock
      .mockResolvedValueOnce(failure(500, 'boom'))
      .mockResolvedValueOnce(answer(page([{ analysis_id: 3, id: 'a' }])))
    const cross = search()
    await cross.run(FILTER)
    await cross.retry()
    expect(searchAcrossAnalysesMock).toHaveBeenCalledTimes(2)
    expect(cross.error.value).toBeUndefined()
    expect(cross.rows.value.map((row) => row.id)).toEqual(['a'])
    cross.stop()
  })

  it('drops the answer to a search that a newer one has replaced', async () => {
    let answerSlow: (value: unknown) => void = () => undefined
    searchAcrossAnalysesMock
      .mockReturnValueOnce(new Promise((resolve) => (answerSlow = resolve)))
      .mockResolvedValueOnce(answer(page([{ analysis_id: 5, id: 'new' }])))
    const cross = search()
    const stale = cross.run({ query: 'old' })
    await cross.run({ query: 'new' })
    answerSlow(answer(page([{ analysis_id: 3, id: 'old' }])))
    await stale
    expect(cross.rows.value.map((row) => row.id)).toEqual(['new'])
    cross.stop()
  })

  it('flips the sort and asks again with the same filter', async () => {
    searchAcrossAnalysesMock.mockResolvedValue(answer(page([{ analysis_id: 3, id: 'a' }])))
    const cross = search()
    await cross.run(FILTER)
    await cross.toggleSort()
    expect(searchAcrossAnalysesMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ body: expect.objectContaining({ ...FILTER, sort: '-@timestamp' }) }),
    )
    cross.stop()
  })

  it('forgets the search when cleared', async () => {
    searchAcrossAnalysesMock.mockResolvedValue(answer(page([{ analysis_id: 3, id: 'a' }])))
    const cross = search()
    await cross.run(FILTER)
    cross.clear()
    expect(cross.searched.value).toBe(false)
    expect(cross.rows.value).toEqual([])
    cross.stop()
  })
})
