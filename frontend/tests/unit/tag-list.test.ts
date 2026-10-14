import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import TagChip from '@/components/TagChip.vue'
import TagList from '@/components/TagList.vue'

const mountList = (tags: string[], max?: number) =>
  mount(TagList, { global: { plugins: [Quasar] }, props: { tags, ...(max !== undefined && { max }) } })

describe('TagList', () => {
  it('shows nothing for an analysis without tags', () => {
    const wrapper = mountList([])
    expect(wrapper.findAllComponents(TagChip)).toHaveLength(0)
    expect(wrapper.find('.tag-list__more').exists()).toBe(false)
  })

  it('shows every tag up to the limit', () => {
    const wrapper = mountList(['a', 'b'])
    expect(wrapper.findAllComponents(TagChip).map((chip) => chip.props('name'))).toEqual(['a', 'b'])
    expect(wrapper.find('.tag-list__more').exists()).toBe(false)
  })

  it('folds the rest into +N, with all names as its title', () => {
    const wrapper = mountList(['a', 'b', 'c', 'd'], 2)
    expect(wrapper.findAllComponents(TagChip).map((chip) => chip.props('name'))).toEqual(['a', 'b'])
    const more = wrapper.get('.tag-list__more')
    expect(more.text()).toBe('+2')
    expect(more.attributes('title')).toBe('c, d')
  })
})
