import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AboutCard from '@/components/AboutCard.vue'

const systemVersion = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ systemVersion }))

const LOADED = { version: '1.0.0', commit: 'abc1234', license: 'GPL-3.0-only' }

function mountCard() {
  return mount(AboutCard, { global: { plugins: [Quasar] } })
}

beforeEach(() => {
  systemVersion.mockReset()
  systemVersion.mockResolvedValue({ data: LOADED, response: { status: 200 } })
})

describe('AboutCard', () => {
  it('shows a loader while the version is requested', () => {
    systemVersion.mockReturnValue(new Promise(() => undefined))
    const wrapper = mountCard()

    expect(wrapper.find('.loader').attributes('aria-label')).toBe('Loading version')
    expect(wrapper.find('.about-version').exists()).toBe(false)
  })

  it('shows the name, version, commit and license once loaded', async () => {
    const wrapper = mountCard()
    await flushPromises()

    expect(wrapper.find('.loader').exists()).toBe(false)
    expect(wrapper.find('.about-name').text()).toBe('Tartarus')
    expect(wrapper.find('.about-version').text()).toBe('1.0.0')
    expect(wrapper.find('.about-commit').text()).toBe('abc1234')
    expect(wrapper.find('.about-license').text()).toBe('GPL-3.0-only')
  })

  it('leaves the commit out when the backend reports none', async () => {
    systemVersion.mockResolvedValue({ data: { ...LOADED, commit: null }, response: { status: 200 } })
    const wrapper = mountCard()
    await flushPromises()

    expect(wrapper.find('.about-commit').exists()).toBe(false)
    expect(wrapper.find('.about-version').text()).toBe('1.0.0')
  })

  it('links the license and the third-party notices on GitHub, opened without a referrer', async () => {
    const wrapper = mountCard()
    await flushPromises()

    const license = wrapper.find('a.about-license-link')
    const thirdParty = wrapper.find('a.about-third-party-link')
    expect(license.attributes('href')).toBe('https://github.com/MainSkown/Tartarus/blob/master/LICENSE')
    expect(thirdParty.attributes('href')).toBe('https://github.com/MainSkown/Tartarus/blob/master/THIRD_PARTY.md')
    for (const link of [license, thirdParty]) {
      expect(link.attributes('target')).toBe('_blank')
      expect(link.attributes('rel')).toBe('noopener noreferrer')
    }
  })

  it('credits MITRE ATT&CK with its copyright line and links the terms of use', async () => {
    const wrapper = mountCard()
    await flushPromises()

    expect(wrapper.find('.about-attribution').text()).toContain(
      'MITRE ATT&CK® data: © 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation.',
    )
    const terms = wrapper.find('a.about-attribution-link')
    expect(terms.attributes('href')).toBe('https://attack.mitre.org/resources/legal-and-branding/terms-of-use/')
    expect(terms.attributes('target')).toBe('_blank')
    expect(terms.attributes('rel')).toBe('noopener noreferrer')
  })

  it('says the version failed to load and retries on the button', async () => {
    systemVersion.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'boom' } }, response: { status: 500 } })
    const wrapper = mountCard()
    await flushPromises()

    expect(wrapper.text()).toContain('> failed to load version')
    expect(wrapper.find('.about-version').exists()).toBe(false)

    await wrapper.find('.about-retry-btn').trigger('click')
    await flushPromises()

    expect(systemVersion).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.about-version').text()).toBe('1.0.0')
  })
})
