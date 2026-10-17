import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import GuestHealthMenu from '@/components/guest/GuestHealthMenu.vue'
import { guestFixture } from './guest-fixtures'

async function mountMenu(props: { guests?: ReturnType<typeof guestFixture>[]; message?: string | null } = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }] })
  await router.push('/')
  return mount(GuestHealthMenu, {
    global: { plugins: [Quasar, router] },
    props: { guests: [guestFixture(), guestFixture({ name: 'lab4', state: 'building', badges: [] })], ...props },
  })
}

describe('GuestHealthMenu', () => {
  it('lists every guest with its state', async () => {
    const wrapper = await mountMenu()
    expect(wrapper.text()).toContain('lab1')
    expect(wrapper.text()).toContain('READY')
    expect(wrapper.text()).toContain('lab4')
    expect(wrapper.text()).toContain('BUILDING')
  })

  it('shows the aggregate message of the health check', async () => {
    const wrapper = await mountMenu({ message: 'degraded: lab4 is building' })
    expect(wrapper.find('.guest-health-menu__message').text()).toBe('degraded: lab4 is building')
  })

  it('shows no message line when the health check has none', async () => {
    const wrapper = await mountMenu({ message: null })
    expect(wrapper.find('.guest-health-menu__message').exists()).toBe(false)
  })

  it('links to the Guest VM page', async () => {
    const wrapper = await mountMenu()
    expect(wrapper.find('a[href="/guest"]').text()).toContain('OPEN GUEST VM')
  })

  it('says there are no guests rather than showing an empty list', async () => {
    const wrapper = await mountMenu({ guests: [] })
    expect(wrapper.text()).toContain('no guests')
  })
})
