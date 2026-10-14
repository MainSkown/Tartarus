import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import type { FieldRead } from '@/api'

const queryFieldsMock = vi.fn()
const queryValuesMock = vi.fn()
vi.mock('@/api', () => ({
  queryFields: (...args: unknown[]) => queryFieldsMock(...args),
  queryValues: (...args: unknown[]) => queryValuesMock(...args),
}))

const { useQuerySuggestions, SUGGESTION_DELAY_MS } = await import('@/composables/use-query-suggestions')

function field(overrides: Partial<FieldRead> & Pick<FieldRead, 'name'>): FieldRead {
  return { type: 'keyword', aliases: [], description: '', example: '', lane: null, members: [], searchable: true, ...overrides }
}

const PROCESS_NAME = field({ name: 'process.name', aliases: ['proc'], example: 'cmd.exe' })
const PROCESS_PID = field({ name: 'process.pid', type: 'long', aliases: ['pid'] })
const CATALOG = [PROCESS_NAME, PROCESS_PID, field({ name: 'file.path', type: 'keyword_with_text' })]

function suggestions(initial = '', caret?: number) {
  const draft = ref(initial)
  const caretRef = ref(caret ?? initial.length)
  const scope = effectScope()
  const result = scope.run(() => useQuerySuggestions(draft, caretRef, () => 7))!
  async function type(text: string): Promise<void> {
    draft.value = text
    caretRef.value = text.length
    result.reveal()
    await nextTick()
  }
  async function settle(): Promise<void> {
    await vi.advanceTimersByTimeAsync(SUGGESTION_DELAY_MS)
    await flushPromises()
  }
  return { draft, caret: caretRef, result, type, settle }
}

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  queryFieldsMock.mockReset()
  queryValuesMock.mockReset()
  queryFieldsMock.mockImplementation(async (options?: { query?: { prefix?: string } }) => {
    const prefix = options?.query?.prefix
    return { data: prefix ? CATALOG.filter((entry) => entry.name.startsWith(prefix)) : CATALOG, error: undefined }
  })
  queryValuesMock.mockResolvedValue({
    data: { values: [{ value: 'cmd.exe', count: 12 }, { value: 'conhost.exe', count: 3 }] },
    error: undefined,
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('field suggestions', () => {
  it('asks the catalog for the typed prefix after a pause', async () => {
    const { type, result } = suggestions()
    await type('pro')
    await vi.advanceTimersByTimeAsync(SUGGESTION_DELAY_MS - 1)
    expect(queryFieldsMock).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(queryFieldsMock).toHaveBeenCalledWith(expect.objectContaining({ query: { prefix: 'pro' } }))
    expect(result.items.value.map((item) => item.kind === 'field' && item.field.name)).toEqual(['process.name', 'process.pid'])
  })

  it('asks once for a burst of typing, about the last prefix', async () => {
    const { type, settle } = suggestions()
    for (const text of ['p', 'pr', 'pro']) {
      await type(text)
      await vi.advanceTimersByTimeAsync(50)
    }
    await settle()
    expect(queryFieldsMock).toHaveBeenCalledTimes(1)
    expect(queryFieldsMock.mock.calls[0]![0].query.prefix).toBe('pro')
  })

  it('offers nothing for an empty prefix instead of listing the whole catalog', async () => {
    const { type, settle, result } = suggestions()
    await type('lane:file ')
    await settle()
    expect(queryFieldsMock).not.toHaveBeenCalled()
    expect(result.items.value).toEqual([])
  })

  it('clears the items at once when the caret leaves a token', async () => {
    const { type, settle, result } = suggestions()
    await type('pro')
    await settle()
    expect(result.items.value).toHaveLength(2)
    await type('pro ')
    expect(result.items.value).toEqual([])
  })

  it('offers nothing when the catalog request fails', async () => {
    queryFieldsMock.mockResolvedValue({ data: undefined, error: { error: { message: 'down' } } })
    const { type, settle, result } = suggestions()
    await type('pro')
    await settle()
    expect(result.items.value).toEqual([])
  })

  it('drops the answer for a prefix that is no longer typed', async () => {
    let resolveFirst: (value: unknown) => void = () => undefined
    queryFieldsMock.mockReturnValueOnce(new Promise((resolve) => (resolveFirst = resolve)))
    const { type, settle, result } = suggestions()
    await type('pro')
    await vi.advanceTimersByTimeAsync(SUGGESTION_DELAY_MS)
    await type('file')
    await settle()
    resolveFirst({ data: [PROCESS_NAME], error: undefined })
    await flushPromises()
    expect(result.items.value.map((item) => item.kind === 'field' && item.field.name)).not.toContain('process.name')
  })
})

describe('value suggestions', () => {
  beforeEach(() => {
    queryFieldsMock.mockImplementation(async (options?: { query?: { prefix?: string } }) => ({
      data: options?.query?.prefix ? [] : CATALOG,
      error: undefined,
    }))
  })

  it('asks for the values of a keyword field, for this analysis', async () => {
    const { type, settle, result } = suggestions()
    await type('process.name:c')
    await settle()
    expect(queryValuesMock).toHaveBeenCalledWith(
      expect.objectContaining({ path: { analysis_id: 7 }, query: { field: 'process.name', prefix: 'c', limit: 10 } }),
    )
    expect(result.items.value).toEqual([
      { kind: 'value', value: 'cmd.exe', count: 12 },
      { kind: 'value', value: 'conhost.exe', count: 3 },
    ])
  })

  it('asks with an empty prefix right after the colon', async () => {
    const { type, settle } = suggestions()
    await type('process.name:')
    await settle()
    expect(queryValuesMock.mock.calls[0]![0].query.prefix).toBe('')
  })

  it('resolves an alias through the catalog', async () => {
    const { type, settle } = suggestions()
    await type('proc:c')
    await settle()
    expect(queryValuesMock).toHaveBeenCalledTimes(1)
  })

  it('offers no values for a field that is not a keyword', async () => {
    const { type, settle, result } = suggestions()
    await type('process.pid:12')
    await settle()
    expect(queryValuesMock).not.toHaveBeenCalled()
    expect(result.items.value).toEqual([])
  })

  it('offers no values for a field the catalog does not know', async () => {
    const { type, settle, result } = suggestions()
    await type('nope:12')
    await settle()
    expect(queryValuesMock).not.toHaveBeenCalled()
    expect(result.items.value).toEqual([])
  })

  it('offers nothing when the values request fails', async () => {
    queryValuesMock.mockResolvedValue({ data: undefined, error: { error: { message: 'down' } } })
    const { type, settle, result } = suggestions()
    await type('process.name:c')
    await settle()
    expect(result.items.value).toEqual([])
  })
})

describe('opening and choosing', () => {
  async function withFieldItems() {
    const harness = suggestions()
    await harness.type('pro')
    await harness.settle()
    return harness
  }

  it('is closed until the user types, even when the caret sits on a token', async () => {
    const { result, settle } = suggestions('pro')
    await settle()
    expect(result.open.value).toBe(false)
  })

  it('opens when there are items for what was typed', async () => {
    const { result } = await withFieldItems()
    expect(result.open.value).toBe(true)
  })

  it('stays closed when there is nothing to offer', async () => {
    const { type, settle, result } = suggestions()
    await type('lane:file ')
    await settle()
    expect(result.open.value).toBe(false)
  })

  it('closes on dismiss and opens again when the user types', async () => {
    const { result, type, settle } = await withFieldItems()
    result.dismiss()
    expect(result.open.value).toBe(false)
    await type('proc')
    await settle()
    expect(result.open.value).toBe(true)
  })

  it('opens a dismissed list again on reveal, for the arrow key', async () => {
    const { result } = await withFieldItems()
    result.dismiss()
    result.reveal()
    expect(result.open.value).toBe(true)
  })

  it('starts with nothing chosen, so Enter still applies the query', async () => {
    const { result } = await withFieldItems()
    expect(result.activeIndex.value).toBe(-1)
    expect(result.active.value).toBeUndefined()
  })

  it('moves down and up, wrapping at both ends', async () => {
    const { result } = await withFieldItems()
    result.move(1)
    expect(result.activeIndex.value).toBe(0)
    result.move(1)
    expect(result.activeIndex.value).toBe(1)
    result.move(1)
    expect(result.activeIndex.value).toBe(0)
    result.move(-1)
    expect(result.activeIndex.value).toBe(1)
  })

  it('goes to the last item on up from nothing chosen', async () => {
    const { result } = await withFieldItems()
    result.move(-1)
    expect(result.activeIndex.value).toBe(1)
  })

  it('does not move when there are no items', () => {
    const { result } = suggestions()
    result.move(1)
    expect(result.activeIndex.value).toBe(-1)
  })

  it('forgets the chosen item when new items arrive', async () => {
    const { result, type, settle } = await withFieldItems()
    result.move(1)
    await type('proc')
    await settle()
    expect(result.activeIndex.value).toBe(-1)
  })

  it('turns an item into what the token takes', async () => {
    const { result } = await withFieldItems()
    result.move(1)
    expect(result.active.value).toBeDefined()
    expect(result.suggestionFor(result.items.value[0]!)).toEqual({ kind: 'field', name: 'process.name' })
    expect(result.suggestionFor({ kind: 'value', value: 'cmd.exe', count: 1 })).toEqual({ kind: 'value', value: 'cmd.exe' })
  })
})
