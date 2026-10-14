import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { failed, succeeded } from './annotation-fixtures'

const annotationsListTagsMock = vi.fn()
vi.mock('@/api', () => ({
  annotationsListTags: (...args: unknown[]) => annotationsListTagsMock(...args),
}))

const { useTagsStore } = await import('@/stores/tags')
const { quietOn } = await import('@/services/quiet-statuses')

const USAGE = [
  { name: 'phishing', count: 7 },
  { name: 'tlp:amber', count: 2 },
  { name: 'emotet', count: 1 },
]

beforeEach(() => {
  setActivePinia(createPinia())
  annotationsListTagsMock.mockReset().mockResolvedValue(succeeded(USAGE))
})

describe('tags store', () => {
  it('lists every tag in use with its count', async () => {
    const store = useTagsStore()
    await store.load()
    expect(store.items).toEqual(USAGE)
    expect(store.loadError).toBeUndefined()
  })

  it('asks quietly: a failed autocomplete is not worth a toast', async () => {
    await useTagsStore().load()
    expect(annotationsListTagsMock).toHaveBeenCalledWith({ meta: quietOn(500, 502, 504) })
  })

  it('keeps what it had when a later read fails', async () => {
    const store = useTagsStore()
    await store.load()
    annotationsListTagsMock.mockResolvedValue(failed('down', 500))
    await store.load()
    expect(store.items).toEqual(USAGE)
    expect(store.loadError).toBe('down')
  })

  it('suggests the names that contain the typed text, most used first, without the ones to leave out', async () => {
    const store = useTagsStore()
    await store.load()
    expect(store.suggest('')).toEqual(USAGE)
    expect(store.suggest('PH')).toEqual([USAGE[0]])
    expect(store.suggest('tl', ['tlp:amber'])).toEqual([])
    expect(store.suggest('m', ['phishing']).map((tag) => tag.name)).toEqual(['tlp:amber', 'emotet'])
  })

  it('caps the suggestions', async () => {
    annotationsListTagsMock.mockResolvedValue(
      succeeded(Array.from({ length: 30 }, (_, index) => ({ name: `tag-${index}`, count: 1 }))),
    )
    const store = useTagsStore()
    await store.load()
    expect(store.suggest('tag')).toHaveLength(8)
  })
})
