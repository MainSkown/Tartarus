import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import ViewState from '@/components/ViewState.vue'

type Props = { loading?: boolean; error?: string; empty?: boolean; emptyMessage?: string }

function mountState(props: Props = {}) {
  return mount(ViewState, {
    props,
    slots: { default: '<p class="content">the view</p>' },
    global: { plugins: [Quasar] },
  })
}

describe('ViewState', () => {
  it('shows the content once there is something to show', () => {
    const wrapper = mountState()
    expect(wrapper.find('.content').exists()).toBe(true)
    expect(wrapper.find('.loader').exists()).toBe(false)
  })

  it('shows only the loader while loading', () => {
    const wrapper = mountState({ loading: true })
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.find('.content').exists()).toBe(false)
  })

  it('shows the error with a retry that asks the owner to reload', async () => {
    const wrapper = mountState({ error: 'index is down' })
    expect(wrapper.text()).toContain('failed to load: index is down')
    expect(wrapper.find('.content').exists()).toBe(false)

    await wrapper.find('.retry-btn').trigger('click')

    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('shows the empty message instead of the content when empty', () => {
    const wrapper = mountState({ empty: true, emptyMessage: 'no processes recorded' })
    expect(wrapper.text()).toContain('> no processes recorded')
    expect(wrapper.find('.content').exists()).toBe(false)
  })

  it('prefers the error over empty, and loading over both', () => {
    expect(mountState({ error: 'x', empty: true }).text()).toContain('failed to load')
    expect(mountState({ loading: true, error: 'x', empty: true }).find('.loader').exists()).toBe(true)
  })
})
