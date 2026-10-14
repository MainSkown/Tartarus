import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it } from 'vitest'
import FieldActions from '@/components/FieldActions.vue'
import { useQueryStateStore } from '@/stores/query-state'

let store: ReturnType<typeof useQueryStateStore>

function mountActions(value: string | number = 'cmd.exe', filterable?: boolean) {
  const pinia = createPinia()
  setActivePinia(pinia)
  store = useQueryStateStore()
  return mount(FieldActions, { props: { field: 'process.name', value, ...(filterable === undefined ? {} : { filterable }) }, global: { plugins: [Quasar, pinia] } })
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('FieldActions', () => {
  it('has a filter on, a filter out and a copy button, each labelled with what it acts on', () => {
    const labels = mountActions()
      .findAll('button')
      .map((button) => button.attributes('aria-label'))
    expect(labels).toEqual(['Filter on process.name: cmd.exe', 'Filter out process.name: cmd.exe', 'Copy process.name value'])
  })

  it('adds a chip that keeps the events with the value on filter on', async () => {
    await mountActions().findAll('button')[0]!.trigger('click')
    expect(store.chips).toEqual([{ field: 'process.name', value: 'cmd.exe', negate: false }])
  })

  it('adds a negated chip on filter out', async () => {
    await mountActions().findAll('button')[1]!.trigger('click')
    expect(store.chips).toEqual([{ field: 'process.name', value: 'cmd.exe', negate: true }])
  })

  it('turns a number into the text a chip holds', async () => {
    await mountActions(4120).findAll('button')[0]!.trigger('click')
    expect(store.chips[0]!.value).toBe('4120')
  })

  it('flips an existing chip rather than adding a second', async () => {
    const wrapper = mountActions()
    await wrapper.findAll('button')[0]!.trigger('click')
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(store.chips).toEqual([{ field: 'process.name', value: 'cmd.exe', negate: true }])
  })

  it('offers only copy for a field the query language cannot filter on', () => {
    const labels = mountActions('x', false)
      .findAll('button')
      .map((button) => button.attributes('aria-label'))
    expect(labels).toEqual(['Copy process.name value'])
  })

  it('emits nothing', async () => {
    const wrapper = mountActions()
    await wrapper.findAll('button')[0]!.trigger('click')
    expect(Object.keys(wrapper.emitted())).not.toContain('add')
  })
})
