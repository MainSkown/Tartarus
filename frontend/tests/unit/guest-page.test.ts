import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { SystemMessage } from '@/services/ws'
import { failed, succeeded } from './annotation-fixtures'
import { buildFixture, guestFixture } from './guest-fixtures'

const api = vi.hoisted(() => ({
  guestsList: vi.fn(),
  guestsProfiles: vi.fn(),
  guestsReadBuild: vi.fn(),
  guestsActiveBuild: vi.fn(),
  guestsCheck: vi.fn(),
  guestsDelete: vi.fn(),
  settingsRead: vi.fn(),
  systemHealth: vi.fn(),
}))
const confirmDestructive = vi.hoisted(() => vi.fn())
let pushMessage: (message: SystemMessage) => void = () => undefined

vi.mock('@/api', () => api)
vi.mock('@/services/confirm', () => ({ confirmDestructive }))
vi.mock('@/services/ws', () => ({
  createSystemClient: () => ({
    state: { value: 'open' },
    subscribe: (handler: (message: SystemMessage) => void) => {
      pushMessage = handler
      return () => undefined
    },
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const GuestPage = (await import('@/pages/GuestPage.vue')).default

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:p(.*)*', component: { template: '<div />' } }],
  })
  await router.push('/guest')
  const wrapper = mount(GuestPage, { global: { plugins: [Quasar, router] } })
  await flushPromises()
  return { wrapper, router }
}

const lab1 = guestFixture()
const lab2 = guestFixture({ name: 'lab2', badges: ['DEFENDER OFF'], kind: 'clone', cloned_from: 'lab1' })
const lab4 = guestFixture({ name: 'lab4', state: 'building', build_id: 'b-lab4', identity: null, selftest: null })

const cards = (wrapper: Awaited<ReturnType<typeof mountPage>>['wrapper']) => wrapper.findAll('.guest-card')
const buttonIn = (root: { findAll: (selector: string) => DOMWrapper<Element>[] }, label: string) =>
  root.findAll('button, a').find((element) => element.text().includes(label))!

beforeEach(() => {
  setActivePinia(createPinia())
  Notify.create = vi.fn()
  api.systemHealth.mockResolvedValue({ data: undefined })
  api.guestsList.mockReset().mockResolvedValue(succeeded([lab1, lab2, lab4]))
  api.guestsProfiles.mockReset().mockResolvedValue(succeeded([{ id: 'windows', display_name: 'Windows 11' }]))
  api.guestsReadBuild.mockReset().mockResolvedValue(succeeded(buildFixture()))
  api.guestsActiveBuild.mockReset().mockResolvedValue(failed('none', 404))
  api.guestsCheck.mockReset()
  api.guestsDelete.mockReset().mockResolvedValue({ data: undefined, error: undefined })
  api.settingsRead.mockReset().mockResolvedValue(succeeded({ default_guest: null }))
  confirmDestructive.mockReset().mockResolvedValue(true)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('GuestPage', () => {
  it('has the GUEST VM heading and a NEW GUEST button to the wizard', async () => {
    const { wrapper } = await mountPage()
    expect(wrapper.find('h1').text()).toBe('GUEST VM')
    expect(buttonIn(wrapper, 'NEW GUEST').attributes('href')).toBe('/guest/new')
  })

  it('shows a card per guest, the default one marked, a building one with its progress', async () => {
    const { wrapper } = await mountPage()
    const all = cards(wrapper)
    expect(all.map((card) => card.find('.guest-card__name').text())).toEqual(['lab1', 'lab2', 'lab4'])
    expect(all[0]!.text()).toContain('DEFAULT')
    expect(all[1]!.text()).not.toContain('DEFAULT')
    expect(all[2]!.text()).toContain('42%')
  })

  it('names the OS from the profile', async () => {
    const { wrapper } = await mountPage()
    expect(cards(wrapper)[0]!.text()).toContain('Windows 11 Pro')
  })

  it('marks the guest of the Settings default instead of the first', async () => {
    api.settingsRead.mockResolvedValue(succeeded({ default_guest: 'lab2' }))
    const { wrapper } = await mountPage()
    expect(cards(wrapper)[0]!.text()).not.toContain('DEFAULT')
    expect(cards(wrapper)[1]!.text()).toContain('DEFAULT')
  })

  it('shows the loader until the first answer', async () => {
    api.guestsList.mockReturnValue(new Promise(() => undefined))
    const { wrapper } = await mountPage()
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.find('.guest-card').exists()).toBe(false)
  })

  it('is the not-built state, with BUILD GUEST and where the ISO goes, when there is no guest', async () => {
    api.guestsList.mockResolvedValue(succeeded([]))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('> guest VM not built')
    expect(wrapper.text()).toContain('data/iso')
    expect(buttonIn(wrapper, 'BUILD GUEST').attributes('href')).toBe('/guest/new')
  })

  it('says the control service is unreachable and offers RETRY, instead of the not-built state', async () => {
    api.guestsList.mockResolvedValue(failed('guest control list: unreachable (connection refused)', 502))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('> guest control service is not reachable')
    expect(wrapper.text()).toContain('unreachable (connection refused)')
    expect(wrapper.text()).not.toContain('guest VM not built')

    api.guestsList.mockResolvedValue(succeeded([lab1]))
    await buttonIn(wrapper, 'RETRY').trigger('click')
    await flushPromises()
    expect(cards(wrapper)).toHaveLength(1)
    expect(wrapper.text()).not.toContain('not reachable')
  })

  it('keeps the cards it has and notes the problem when a later load fails', async () => {
    const { wrapper } = await mountPage()
    api.guestsList.mockResolvedValue(failed('unreachable', 502))
    pushMessage({ type: 'job', job: { id: 1, type: 'guest_build', analysis_id: null, status: 'running', step: '', progress: 0, result: null } } as SystemMessage)
    await flushPromises()
    expect(cards(wrapper)).toHaveLength(3)
    expect(wrapper.text()).toContain('> guest control service is not reachable')
  })

  it('runs the checks of the guest whose button was pressed and shows them on its card', async () => {
    api.guestsCheck.mockResolvedValue(succeeded({ name: 'lab2', checks: [{ id: 'agent', ok: false, message: 'agent silent' }] }))
    const { wrapper } = await mountPage()
    await buttonIn(cards(wrapper)[1]!, 'RUN CHECKS').trigger('click')
    await flushPromises()
    expect(api.guestsCheck.mock.calls[0]![0].path).toEqual({ name: 'lab2' })
    expect(cards(wrapper)[1]!.text()).toContain('agent silent')
    expect(cards(wrapper)[0]!.find('.guest-checks').exists()).toBe(false)
  })

  it('shows the 409 of a refused check on the card', async () => {
    api.guestsCheck.mockResolvedValue(failed('An analysis is queued or running', 409))
    const { wrapper } = await mountPage()
    await buttonIn(cards(wrapper)[0]!, 'RUN CHECKS').trigger('click')
    await flushPromises()
    expect(cards(wrapper)[0]!.find('.guest-checks').text()).toContain('An analysis is queued or running')
  })

  it('deletes after the confirmation and drops the card', async () => {
    const { wrapper } = await mountPage()
    api.guestsList.mockResolvedValue(succeeded([lab1, lab4]))
    await buttonIn(cards(wrapper)[1]!, 'DELETE').trigger('click')
    await flushPromises()
    expect(confirmDestructive.mock.calls[0]![0].title).toBe('Delete lab2')
    expect(api.guestsDelete.mock.calls[0]![0].path).toEqual({ name: 'lab2' })
    expect(cards(wrapper)).toHaveLength(2)
  })

  it('shows the 409 of a refused delete on the card', async () => {
    api.guestsDelete.mockResolvedValue(failed('lab2 cannot be deleted while an analysis runs', 409))
    const { wrapper } = await mountPage()
    await buttonIn(cards(wrapper)[1]!, 'DELETE').trigger('click')
    await flushPromises()
    expect(cards(wrapper)[1]!.find('.guest-card__refusal').text()).toContain('while an analysis runs')
    expect(cards(wrapper)).toHaveLength(3)
  })
})
