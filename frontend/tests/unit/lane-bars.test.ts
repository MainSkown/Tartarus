import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import LaneBars from '@/components/LaneBars.vue'
import { laneBars } from '@/services/lanes'

const BARS = laneBars({ api: 472, network: 217, process: 15, file: 2, registry: 2 })

describe('LaneBars', () => {
  const wrapper = () => mount(LaneBars, { global: { plugins: [Quasar] }, props: { bars: BARS } })

  it('draws one bar per lane with its label and count written out', () => {
    const rows = wrapper().findAll('.lane-bar')
    expect(rows.map((row) => row.find('.lane-bar__label').text())).toEqual(['PROCESS', 'FILE', 'REGISTRY', 'NETWORK', 'API'])
    expect(rows.map((row) => row.find('.lane-bar__count').text())).toEqual(['15', '2', '2', '217', '472'])
  })

  it('sizes the bars against the busiest lane', () => {
    const fills = wrapper().findAll('.lane-bar__fill')
    expect(fills.at(-1)!.attributes('style')).toContain('width: 100%')
    expect(fills[0]!.attributes('style')).toContain('width: 3.17')
  })

  it('colours each bar with its lane colour from the design system', () => {
    const fills = wrapper().findAll('.lane-bar__fill')
    expect(fills[0]!.attributes('style')).toContain('--cat-process')
    expect(fills.at(-1)!.attributes('style')).toContain('--cat-api')
  })

  it('is a list a screen reader can read', () => {
    const list = wrapper().find('ul')
    expect(list.attributes('aria-label')).toBe('Events by lane')
    expect(list.findAll('li')).toHaveLength(5)
  })
})
