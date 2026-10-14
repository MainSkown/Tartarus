import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { FieldRead } from '@/api'

const queryFieldsMock = vi.fn()
vi.mock('@/api', () => ({ queryFields: (...args: unknown[]) => queryFieldsMock(...args) }))

const { useEventColumnsStore, COLUMNS_STORAGE_KEY } = await import('@/stores/event-columns')
const { MAX_COLUMNS } = await import('@/services/event-columns')

function field(name: string, overrides: Partial<FieldRead> = {}): FieldRead {
  return { name, type: 'keyword', aliases: [], description: '', example: '', lane: null, members: [], searchable: true, ...overrides }
}

const CATALOG = [
  field('file.path'),
  field('api.name'),
  field('process.command_line'),
  field('domain', { members: ['dns.question.name', 'destination.domain'] }),
  field('tartarus.raw', { type: 'object_disabled', searchable: false }),
  ...Array.from({ length: 14 }, (_, index) => field(`extra.field${index}`)),
]

function freshStore() {
  setActivePinia(createPinia())
  return useEventColumnsStore()
}

beforeEach(() => {
  queryFieldsMock.mockReset()
  queryFieldsMock.mockResolvedValue({ data: CATALOG })
})

afterEach(() => window.localStorage.clear())

describe('choosing', () => {
  it('starts with no extra columns', () => {
    expect(freshStore().chosen).toEqual([])
  })

  it('adds and removes a column, in the order chosen', () => {
    const columns = freshStore()
    columns.toggle('file.path')
    columns.toggle('api.name')
    expect(columns.chosen).toEqual(['file.path', 'api.name'])
    expect(columns.isChosen('api.name')).toBe(true)
    columns.toggle('file.path')
    expect(columns.chosen).toEqual(['api.name'])
  })

  it('clears the choice', () => {
    const columns = freshStore()
    columns.toggle('file.path')
    columns.clear()
    expect(columns.chosen).toEqual([])
  })
})

describe('the limit', () => {
  it('refuses a column beyond the most a search can return, and says it is at the limit', () => {
    const columns = freshStore()
    for (let index = 0; index < MAX_COLUMNS + 2; index++) columns.toggle(`extra.field${index}`)
    expect(columns.chosen).toHaveLength(MAX_COLUMNS)
    expect(columns.atLimit).toBe(true)
    expect(columns.isChosen(`extra.field${MAX_COLUMNS}`)).toBe(false)
  })

  it('still removes a column at the limit, which frees a place', () => {
    const columns = freshStore()
    for (let index = 0; index < MAX_COLUMNS; index++) columns.toggle(`extra.field${index}`)
    columns.toggle('extra.field0')
    expect(columns.atLimit).toBe(false)
    columns.toggle('extra.field13')
    expect(columns.isChosen('extra.field13')).toBe(true)
  })

  it('is twelve', () => {
    expect(MAX_COLUMNS).toBe(12)
  })
})

describe('remembering', () => {
  it('remembers the choice for the next visit', async () => {
    freshStore().toggle('file.path')
    await nextTick()
    expect(freshStore().chosen).toEqual(['file.path'])
  })

  it('reads a remembered value that is not a list of names as no choice', () => {
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, '"nonsense"')
    expect(freshStore().chosen).toEqual([])
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(['file.path', 7, 'api.name']))
    expect(freshStore().chosen).toEqual(['file.path', 'api.name'])
  })

  it('keeps no more than the limit of a remembered list', () => {
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(Array.from({ length: 20 }, (_, index) => `extra.field${index % 14}${index}`)))
    expect(freshStore().chosen).toHaveLength(MAX_COLUMNS)
  })

  it('drops a remembered name that is no longer a catalog field once the catalog is known, and keeps the rest', async () => {
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(['file.path', 'gone.field', 'domain', 'tartarus.raw', 'api.name']))
    const columns = freshStore()
    await columns.validate()
    expect(columns.chosen).toEqual(['file.path', 'api.name'])
    await nextTick()
    expect(JSON.parse(window.localStorage.getItem(COLUMNS_STORAGE_KEY)!)).toEqual(['file.path', 'api.name'])
  })

  it('keeps the remembered names when the catalog could not be loaded', async () => {
    queryFieldsMock.mockResolvedValue({ data: undefined })
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(['file.path']))
    const columns = freshStore()
    await columns.validate()
    expect(columns.chosen).toEqual(['file.path'])
  })

  it('does not ask for the catalog when nothing is chosen', async () => {
    await freshStore().validate()
    expect(queryFieldsMock).not.toHaveBeenCalled()
  })

  it('accepts an alias of a catalog field as the field', async () => {
    queryFieldsMock.mockResolvedValue({ data: [field('process.name', { aliases: ['proc'] })] })
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(['proc']))
    const columns = freshStore()
    await columns.validate()
    expect(columns.chosen).toEqual(['process.name'])
  })
})
