import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FieldRead } from '@/api'

const queryFieldsMock = vi.fn()
vi.mock('@/api', () => ({ queryFields: (...args: unknown[]) => queryFieldsMock(...args) }))

const { useFieldCatalogStore } = await import('@/stores/field-catalog')

function field(overrides: Partial<FieldRead> & Pick<FieldRead, 'name'>): FieldRead {
  return {
    type: 'keyword',
    aliases: [],
    description: '',
    example: '',
    lane: null,
    members: [],
    searchable: true,
    ...overrides,
  }
}

const CATALOG: FieldRead[] = [
  field({ name: 'process.name', aliases: ['proc', 'process'] }),
  field({ name: 'file.path', type: 'keyword_with_text', aliases: ['path'] }),
  field({ name: 'destination.port', type: 'long', aliases: ['port', 'dst.port'] }),
  field({ name: 'rule.description', type: 'text' }),
  field({ name: 'domain', members: ['dns.question.name', 'destination.domain'] }),
  field({ name: 'tartarus.raw', type: 'object_disabled', searchable: false }),
]

let catalog: Awaited<ReturnType<typeof useFieldCatalogStore>>

beforeEach(() => {
  queryFieldsMock.mockReset()
  queryFieldsMock.mockResolvedValue({ data: CATALOG, error: undefined })
  setActivePinia(createPinia())
  catalog = useFieldCatalogStore()
})

describe('canonicalName', () => {
  it('names the field an alias stands for, in any case, and leaves a canonical name or an unknown one as it is', async () => {
    await catalog.load()
    expect(catalog.canonicalName('proc')).toBe('process.name')
    expect(catalog.canonicalName('PORT')).toBe('destination.port')
    expect(catalog.canonicalName('process.name')).toBe('process.name')
    expect(catalog.canonicalName('nope')).toBe('nope')
  })
})

describe('loading', () => {
  it('asks for the whole catalog, without a prefix', async () => {
    await catalog.load()
    expect(queryFieldsMock).toHaveBeenCalledTimes(1)
    expect(queryFieldsMock.mock.calls[0]![0]?.query?.prefix).toBeUndefined()
    expect(catalog.fields).toEqual(CATALOG)
  })

  it('asks once, however many times and however fast it is asked for', async () => {
    await Promise.all([catalog.load(), catalog.load()])
    await catalog.load()
    expect(queryFieldsMock).toHaveBeenCalledTimes(1)
  })

  it('stays empty after a failure and asks again the next time', async () => {
    queryFieldsMock.mockResolvedValueOnce({ data: undefined, error: { error: { message: 'down' } } })
    await catalog.load()
    expect(catalog.fields).toEqual([])
    await catalog.load()
    expect(catalog.fields).toEqual(CATALOG)
  })

  it('does not toast when the request fails, the bar works without it', async () => {
    await catalog.load()
    expect(queryFieldsMock.mock.calls[0]![0]?.meta?.quietStatuses).toEqual(expect.arrayContaining([500, 502, 504]))
  })
})

describe('finding a field', () => {
  beforeEach(async () => {
    await catalog.load()
    await flushPromises()
  })

  it('finds by name or alias, ignoring case', () => {
    expect(catalog.find('process.name')?.name).toBe('process.name')
    expect(catalog.find('PROC')?.name).toBe('process.name')
    expect(catalog.find('Dst.Port')?.name).toBe('destination.port')
  })

  it('finds a composite alias', () => {
    expect(catalog.find('domain')?.members).toHaveLength(2)
  })

  it('finds nothing for an unknown name', () => {
    expect(catalog.find('nope')).toBeUndefined()
  })

  it('offers values for keyword fields, with or without a text subfield, and for a composite alias', () => {
    expect(catalog.offersValues('process.name')).toBe(true)
    expect(catalog.offersValues('path')).toBe(true)
    expect(catalog.offersValues('domain')).toBe(true)
  })

  it('offers no values for numbers, text, unsearchable or unknown fields', () => {
    expect(catalog.offersValues('destination.port')).toBe(false)
    expect(catalog.offersValues('rule.description')).toBe(false)
    expect(catalog.offersValues('tartarus.raw')).toBe(false)
    expect(catalog.offersValues('nope')).toBe(false)
  })

  it('lists every alias with the field it stands for, sorted by alias', () => {
    const rows = catalog.aliasRows
    expect(rows.map((row) => row.alias)).toEqual(['domain', 'dst.port', 'path', 'port', 'proc', 'process'])
    expect(rows.find((row) => row.alias === 'path')).toEqual({ alias: 'path', field: 'file.path' })
  })

  it('writes a composite alias as the fields it stands for', () => {
    expect(catalog.aliasRows.find((row) => row.alias === 'domain')?.field).toBe('dns.question.name OR destination.domain')
  })
})
