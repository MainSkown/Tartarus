import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { failed, succeeded } from './annotation-fixtures'
import { guestFixture } from './guest-fixtures'
import { windowsProfile } from './guest-wizard-fixtures'

const api = vi.hoisted(() => ({ guestsProfiles: vi.fn(), guestsList: vi.fn(), guestsClone: vi.fn() }))
vi.mock('@/api', () => api)

const GuestClonePage = (await import('@/pages/GuestClonePage.vue')).default

async function mountPage(name = 'lab1') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/guest/clone/:name', component: { template: '<div />' } }, { path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  await router.push(`/guest/clone/${name}`)
  const wrapper = mount(GuestClonePage, { global: { plugins: [Quasar, router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  setActivePinia(createPinia())
  api.guestsList.mockReset().mockResolvedValue(
    succeeded([
      guestFixture({ options: { defender: false, decoys: true, sysmon: true, key: '', keyboard: 'US' } }),
      guestFixture({ name: 'lab4', state: 'building' }),
    ]),
  )
  api.guestsProfiles.mockReset().mockResolvedValue(succeeded([windowsProfile()]))
  api.guestsClone.mockReset().mockResolvedValue(succeeded({ job_id: 1, build_id: 'b2', guest: 'lab6' }))
})

describe('GuestClonePage', () => {
  it('names the source in the heading with its state and badges', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.find('h1').text()).toBe('CLONE lab1')
    expect(wrapper.text()).toContain('READY')
    expect(wrapper.text()).toContain('DEFENDER ON')
  })

  it('shows the loader while the guests are being read', async () => {
    api.guestsList.mockReturnValue(new Promise(() => undefined))
    const { wrapper } = await mountPage()
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
  })

  it('shows a failure with RETRY', async () => {
    api.guestsList.mockResolvedValue(failed('The guest control service is not reachable', 502))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('failed to load: The guest control service is not reachable')
  })

  it('says the source is unknown and links back to /guest', async () => {
    const { wrapper } = await mountPage('nobody')
    expect(wrapper.text()).toContain('There is no guest called nobody.')
    expect(wrapper.get('a.clone-back').attributes('href')).toBe('/guest')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('says the source is not ready and links back to /guest', async () => {
    const { wrapper } = await mountPage('lab4')
    expect(wrapper.text()).toContain('lab4 is building: only a ready guest can be cloned.')
    expect(wrapper.get('a.clone-back').attributes('href')).toBe('/guest')
  })

  it('says a blank computer name is chosen at clone time', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.find('input[placeholder="chosen at clone time"]').exists()).toBe(true)
  })

  it('says what a clone does and that it blocks analyses', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain("Copies lab1's disk")
    expect(wrapper.text()).toContain('No analysis can start until it is done.')
  })

  it('makes the options a clone may change editable and greys the rest, with the source values', async () => {
    const { wrapper } = await mountPage()
    const fields = wrapper.findAll('.option-field')
    expect(fields.map((field) => field.classes().includes('option-field--locked'))).toEqual([false, false, true, true, true])
  })

  it('shows the username read-only with the reason, and the disk locked', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('A different username needs a build')
    const account = wrapper.findAll('input').find((input) => (input.element as HTMLInputElement).value === 'Marta')!
    expect(account.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain("A clone has its source's disk.")
  })

  it('cannot clone without a name, then clones and goes to the build page', async () => {
    const { wrapper, router } = await mountPage()
    const clone = wrapper.findAll('button').find((element) => element.text().includes('[CLONE]'))!
    expect(clone.attributes('disabled')).toBeDefined()
    await wrapper.find('.name-field input').setValue('lab6')
    expect(clone.attributes('disabled')).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(api.guestsClone).toHaveBeenCalledWith(expect.objectContaining({ path: { name: 'lab1' } }))
    expect(router.currentRoute.value.fullPath).toBe('/guest/builds/b2')
  })

  it('shows a conflict in a banner', async () => {
    api.guestsClone.mockResolvedValue(failed('Another guest is being built: lab4', 409))
    const { wrapper } = await mountPage()
    await wrapper.find('.name-field input').setValue('lab6')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Another guest is being built: lab4')
  })
})
