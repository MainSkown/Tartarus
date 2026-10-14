import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import TagChip from '@/components/TagChip.vue'

const mountChip = (props: { name: string; removable?: boolean }) => mount(TagChip, { global: { plugins: [Quasar] }, props })

describe('TagChip', () => {
  it('shows the name, and the whole name as its title for the cut-off case', () => {
    const wrapper = mountChip({ name: 'tlp:amber' })
    expect(wrapper.text()).toBe('tlp:amber')
    expect(wrapper.attributes('title')).toBe('tlp:amber')
  })

  it('has no remove button unless it is removable', () => {
    expect(mountChip({ name: 'emotet' }).find('button').exists()).toBe(false)
  })

  it('announces which tag the remove button removes, and says so when clicked', async () => {
    const wrapper = mountChip({ name: 'emotet', removable: true })
    const button = wrapper.get('button')
    expect(button.attributes('aria-label')).toBe('Remove tag emotet')
    await button.trigger('click')
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })
})
