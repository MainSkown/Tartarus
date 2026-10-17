import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { failed, succeeded } from './annotation-fixtures'
import { BROKEN_MEDIA, mediaEntry, windowsProfile } from './guest-wizard-fixtures'

const api = vi.hoisted(() => ({
  guestsMedia: vi.fn(),
  guestsProfiles: vi.fn(),
  guestsList: vi.fn(),
  guestsStartBuild: vi.fn(),
}))
vi.mock('@/api', () => api)

const GuestWizardPage = (await import('@/pages/GuestWizardPage.vue')).default

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  await router.push('/guest/new')
  const wrapper = mount(GuestWizardPage, { global: { plugins: [Quasar, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, router }
}

const button = (wrapper: Awaited<ReturnType<typeof mountPage>>['wrapper'], label: string) =>
  wrapper.findAll('button').find((element) => element.text().includes(label))!

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  api.guestsMedia.mockReset().mockResolvedValue(succeeded([mediaEntry(), BROKEN_MEDIA]))
  api.guestsProfiles.mockReset().mockResolvedValue(succeeded([windowsProfile()]))
  api.guestsList.mockReset().mockResolvedValue(succeeded([]))
  api.guestsStartBuild.mockReset().mockResolvedValue(succeeded({ job_id: 1, build_id: 'b1', guest: 'lab5' }))
})

describe('GuestWizardPage', () => {
  it('shows the loader while the media are being read', async () => {
    api.guestsMedia.mockReturnValue(new Promise(() => undefined))
    const { wrapper } = await mountPage()
    expect(wrapper.find('[role="status"]').exists()).toBe(true)
  })

  it('lists the media, with the broken one disabled', async () => {
    const { wrapper } = await mountPage()
    const rows = wrapper.findAll('[role="radio"]')
    expect(rows).toHaveLength(2)
    expect(rows[1]!.attributes('aria-disabled')).toBe('true')
  })

  it('shows the empty state with where to put the ISO', async () => {
    api.guestsMedia.mockResolvedValue(succeeded([]))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('no installation media found')
    expect(wrapper.text()).toContain('data/iso')
  })

  it('shows the failure with RETRY, and reads again on RETRY', async () => {
    api.guestsMedia.mockResolvedValueOnce(failed('The guest control service is not reachable', 502))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('failed to load: The guest control service is not reachable')
    await button(wrapper, '[RETRY]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[role="radio"]')).toHaveLength(2)
  })

  it('cannot continue until a medium is chosen', async () => {
    const { wrapper } = await mountPage()
    expect(button(wrapper, '[CONTINUE]').attributes('disabled')).toBeDefined()
    await wrapper.findAll('[role="radio"]')[0]!.trigger('click')
    expect(button(wrapper, '[CONTINUE]').attributes('disabled')).toBeUndefined()
  })

  it('renders the settings from the profile: one control per option, with its help', async () => {
    const { wrapper } = await mountPage()
    await wrapper.findAll('[role="radio"]')[0]!.trigger('click')
    await button(wrapper, '[CONTINUE]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.option-field')).toHaveLength(5)
    expect(wrapper.text()).toContain('Microsoft Defender')
    expect(wrapper.text()).toContain('Left on, a sample meets Defender')
    expect(wrapper.text()).toContain('Only Tartarus sees this name; Windows never does.')
    expect(wrapper.text()).toContain('USERNAME')
  })

  it('goes through the review to the build page', async () => {
    const { wrapper, router } = await mountPage()
    await wrapper.findAll('[role="radio"]')[0]!.trigger('click')
    await button(wrapper, '[CONTINUE]').trigger('click')
    await flushPromises()
    await wrapper.find('.name-field input').setValue('lab5')
    await button(wrapper, '[CONTINUE]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('The build takes about 15 minutes')
    expect(wrapper.text()).toContain('chosen at build time')
    await button(wrapper, '[BUILD GUEST]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/guest/builds/b1')
  })
})
