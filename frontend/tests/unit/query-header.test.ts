import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api', () => ({
  queryFields: vi.fn().mockResolvedValue({ data: [], error: undefined }),
  queryValues: vi.fn().mockResolvedValue({ data: { values: [] }, error: undefined }),
  queryValidate: vi.fn().mockResolvedValue({ data: { ok: true, errors: [] }, error: undefined }),
}))

const { default: QueryHeader } = await import('@/components/QueryHeader.vue')
const { useQueryStateStore } = await import('@/stores/query-state')

function mountHeader() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useQueryStateStore()
  const wrapper = mount(QueryHeader, { props: { analysisId: 7 }, global: { plugins: [Quasar, pinia] } })
  return { wrapper, store }
}

describe('QueryHeader', () => {
  it('is the bar with no chips under it when nothing is filtered', () => {
    const { wrapper } = mountHeader()
    expect(wrapper.find('.terminal-input-group').exists()).toBe(true)
    expect(wrapper.find('.filter-chip').exists()).toBe(false)
  })

  it('shows the chips of the shared state under the bar', async () => {
    const { wrapper, store } = mountHeader()
    store.addChip({ field: 'lane', value: 'file', negate: false })
    store.setPids([4120])
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.filter-chip')).toHaveLength(2)
    const bar = wrapper.find('.query-bar').element
    const chips = wrapper.find('.filter-chips').element
    expect(bar.compareDocumentPosition(chips) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('binds the bar to the analysis', () => {
    const { wrapper } = mountHeader()
    expect(wrapper.findComponent({ name: 'QueryBar' }).props('analysisId')).toBe(7)
  })
})
