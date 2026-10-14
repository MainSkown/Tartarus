import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FieldRead } from '@/api'

const queryFieldsMock = vi.fn()
vi.mock('@/api', () => ({ queryFields: (...args: unknown[]) => queryFieldsMock(...args) }))

const { default: EventFieldsTable } = await import('@/components/EventFieldsTable.vue')
const { useQueryStateStore } = await import('@/stores/query-state')

function field(name: string, overrides: Partial<FieldRead> = {}): FieldRead {
  return { name, type: 'keyword', aliases: [], description: '', example: '', lane: null, members: [], searchable: true, ...overrides }
}

const CATALOG = [field('process.name'), field('process.command_line', { type: 'keyword_with_text' }), field('domain', { members: ['dns.question.name', 'destination.domain'] })]

let query: ReturnType<typeof useQueryStateStore>

async function mountTable(fields: { name: string; value: string }[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  query = useQueryStateStore()
  const wrapper = mount(EventFieldsTable, { props: { fields }, global: { plugins: [Quasar, pinia] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  queryFieldsMock.mockReset()
  queryFieldsMock.mockResolvedValue({ data: CATALOG })
})

describe('EventFieldsTable', () => {
  it('lists each field with its value', async () => {
    const wrapper = await mountTable([
      { name: 'process.name', value: 'cmd.exe' },
      { name: 'process.pid', value: '2476' },
    ])
    const rows = wrapper.findAll('.field-row')
    expect(rows.map((row) => row.find('.field-row__name').text())).toEqual(['process.name', 'process.pid'])
    expect(rows.map((row) => row.find('.field-row__value').text())).toEqual(['cmd.exe', '2476'])
  })

  it('offers filter on, filter out and copy for a field of the catalog', async () => {
    const wrapper = await mountTable([{ name: 'process.name', value: 'cmd.exe' }])
    const labels = wrapper.findAll('.field-row button').map((button) => button.attributes('aria-label'))
    expect(labels).toEqual(['Filter on process.name: cmd.exe', 'Filter out process.name: cmd.exe', 'Copy process.name value'])
  })

  it('adds a chip from the row', async () => {
    const wrapper = await mountTable([{ name: 'process.name', value: 'cmd.exe' }])
    await wrapper.find('.field-row button').trigger('click')
    expect(query.chips).toEqual([{ field: 'process.name', value: 'cmd.exe', negate: false }])
  })

  it('offers only copy for a field the catalog does not know and for a composite alias', async () => {
    const wrapper = await mountTable([
      { name: 'api.arguments.FileName', value: 'a.ps1' },
      { name: 'domain', value: 'example.com' },
    ])
    for (const row of wrapper.findAll('.field-row')) {
      expect(row.findAll('button').map((button) => button.attributes('aria-label'))).toHaveLength(1)
    }
  })

  it('shows a value that was an empty string as an empty cell and keeps the row', async () => {
    const wrapper = await mountTable([{ name: 'registry.value', value: '' }])
    expect(wrapper.findAll('.field-row')).toHaveLength(1)
  })

  it('keeps a very long value in its cell so it can wrap', async () => {
    const long = `C:\\${'very-long-directory-name\\'.repeat(20)}payload.exe`
    const wrapper = await mountTable([{ name: 'process.command_line', value: long }])
    expect(wrapper.find('.field-row__value').text()).toBe(long)
  })
})
