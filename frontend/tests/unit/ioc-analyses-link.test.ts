import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { filterEventsPlugins } from './filter-events-plugins'

const iocsAnalyses = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ iocsAnalyses }))

const IocAnalysesLink = (await import('@/components/IocAnalysesLink.vue')).default

const { plugins } = await filterEventsPlugins()

async function mountLink(kind: 'ip' | 'domain' | 'mutex', value: string) {
  const wrapper = mount(IocAnalysesLink, { attachTo: document.body, global: { plugins }, props: { kind, value } })
  await flushPromises()
  return wrapper
}

const chip = (wrapper: Awaited<ReturnType<typeof mountLink>>) => wrapper.find('.ioc-analyses__chip')

beforeEach(() => {
  iocsAnalyses.mockReset()
  iocsAnalyses.mockResolvedValue({
    data: [
      { analysis_id: 45, count: 12 },
      { analysis_id: 51, count: 1 },
      { analysis_id: 60, count: 1500 },
    ],
    response: { status: 200 },
  })
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('IocAnalysesLink', () => {
  it('asks the analyses of the indicator it is given', async () => {
    await mountLink('ip', '203.0.113.7')
    expect(iocsAnalyses).toHaveBeenCalledWith(expect.objectContaining({ path: { kind: 'ip', value: '203.0.113.7' } }))
  })

  it('shows nothing while the analyses are loading', () => {
    const wrapper = mount(IocAnalysesLink, { attachTo: document.body, global: { plugins }, props: { kind: 'ip', value: '203.0.113.8' } })
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('counts every analysis the indicator is in, in the chip', async () => {
    const wrapper = await mountLink('ip', '203.0.113.9')
    expect(chip(wrapper).text()).toBe('Seen in 3 analyses')
  })

  it('uses the singular for one analysis', async () => {
    iocsAnalyses.mockResolvedValue({ data: [{ analysis_id: 45, count: 2 }], response: { status: 200 } })
    const wrapper = await mountLink('domain', 'single.example')
    expect(chip(wrapper).text()).toBe('Seen in 1 analysis')
  })

  it('shows nothing for a 422, which means the kind cannot be pivoted', async () => {
    iocsAnalyses.mockResolvedValue({ error: { error: { code: 'x', message: 'mutex' } }, response: { status: 422 } })
    const wrapper = await mountLink('mutex', 'Global\\nothing')
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.find('.ioc-analyses__failed').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('shows a muted icon with a tooltip when the analyses cannot be loaded', async () => {
    iocsAnalyses.mockResolvedValue({ error: { error: { code: 'x', message: 'boom' } }, response: { status: 500 } })
    const wrapper = await mountLink('domain', 'broken.example')
    const failed = wrapper.get('.ioc-analyses__failed')
    expect(failed.attributes('title')).toBe('The analyses holding this indicator could not be loaded')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('opens a menu that links each analysis to its page with its event count', async () => {
    const wrapper = await mountLink('ip', '203.0.113.10')
    await chip(wrapper).trigger('click')
    await flushPromises()

    const items = [...document.querySelectorAll('.ioc-analyses__menu .q-item')]
    expect(items.map((item) => item.getAttribute('href'))).toEqual(['/analyses/45', '/analyses/51', '/analyses/60'])
    expect(items.map((item) => item.textContent?.trim())).toEqual([
      expect.stringContaining('12 events'),
      expect.stringContaining('1 event'),
      expect.stringContaining('1,500 events'),
    ])
  })
})
