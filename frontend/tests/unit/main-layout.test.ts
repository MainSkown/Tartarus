import { mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SystemHealth } from '@/api'

const HEALTHY: SystemHealth = {
  postgres: { status: 'ok', message: null },
  opensearch: { status: 'ok', message: null },
  cape: { status: 'down', message: 'not set up yet' },
  guest: { status: 'down', message: 'not set up yet' },
}

vi.mock('@/api', () => ({
  systemHealth: vi.fn().mockResolvedValue({ data: undefined }),
  settingsRead: vi.fn().mockResolvedValue({ data: undefined, error: {} }),
  analysesList: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  analysesRead: vi.fn().mockResolvedValue({ data: undefined, error: {} }),
}))

vi.mock('@/services/submit-dialog', () => ({ openSubmitDialog: vi.fn() }))

vi.mock('@/services/ws', () => ({
  createSystemHealthClient: () => ({
    state: { value: 'open' },
    lastMessage: { value: undefined },
    subscribe: () => () => undefined,
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const { createAppRouter } = await import('@/router')
// Mounting App.vue (bare `<router-view/>`) rather than MainLayout directly matters here:
// MainLayout's own nested <router-view/> resolves its matched route by depth, counting from
// whatever <router-view/> is already above it. Mounting MainLayout as the test root would put
// its router-view at depth 0, resolving right back to MainLayout itself instead of the page.
const App = (await import('@/App.vue')).default
const { useSystemStore } = await import('@/stores/system')
const { openSubmitDialog } = await import('@/services/submit-dialog')

const GUEST_READY: SystemHealth = { ...HEALTHY, guest: { status: 'ok', message: null } }

async function mountShellAt(path: string) {
  setActivePinia(createPinia())
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const store = useSystemStore()
  store.health = HEALTHY
  const wrapper = mount(App, { global: { plugins: [Quasar, router] } })
  await wrapper.vm.$nextTick()
  return { wrapper, store }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MainLayout', () => {
  it.each([
    '/',
    '/rules',
    '/guest',
    '/settings',
    '/analyses/42',
    '/analyses/42/events',
    '/no/such/route',
  ])('renders %s without throwing', async (path) => {
    const { wrapper } = await mountShellAt(path)
    expect(wrapper.exists()).toBe(true)
  })

  it('shows the wordmark and the three health dots', async () => {
    const { wrapper } = await mountShellAt('/')
    expect(wrapper.text()).toContain('TARTARUS')
    const dots = wrapper.findAll('.health-dot')
    expect(dots).toHaveLength(3)
    expect(dots.map((dot) => dot.attributes('aria-label'))).toEqual([
      expect.stringContaining('CAPE'),
      expect.stringContaining('Guest'),
      expect.stringContaining('Store'),
    ])
  })

  it('hides the reconnect bar while the connection is open', async () => {
    const { wrapper } = await mountShellAt('/')
    expect(wrapper.find('.reconnect-bar').exists()).toBe(false)
  })

  it('shows the reconnect bar while reconnecting', async () => {
    const { wrapper, store } = await mountShellAt('/')
    store.connectionState = 'reconnecting'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.reconnect-bar').exists()).toBe(true)
  })

  it('renders the reconnect bar inside the fixed header, where nothing can cover it', async () => {
    // Outside q-header it sat in the page flow under the fixed header, which painted over it:
    // present in the DOM, taking up space, invisible on screen.
    const { wrapper, store } = await mountShellAt('/')
    store.connectionState = 'reconnecting'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.q-header .reconnect-bar').exists()).toBe(true)
  })

  it('hides the reconnect bar during the very first connect, but shows it once closed', async () => {
    const { wrapper, store } = await mountShellAt('/')
    store.connectionState = 'connecting'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.reconnect-bar').exists()).toBe(false)

    store.connectionState = 'closed'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.reconnect-bar').exists()).toBe(true)
  })

  it('disables the Submit button and reflects the guest health message as the reason', async () => {
    const { wrapper, store } = await mountShellAt('/')
    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.submit-wrapper').attributes('aria-label')).toBe('not set up yet')

    store.health = { ...HEALTHY, guest: { status: 'down', message: 'a different guest reason' } }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.submit-wrapper').attributes('aria-label')).toBe('a different guest reason')
  })

  it('enables the Submit button, with no disabled reason, once the guest is ready', async () => {
    const { wrapper, store } = await mountShellAt('/')
    store.health = GUEST_READY
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.submit-btn').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.submit-wrapper').attributes('aria-label')).toBeUndefined()
  })

  it('opens the Submit dialog when the enabled Submit button is clicked', async () => {
    const { wrapper, store } = await mountShellAt('/')
    store.health = GUEST_READY
    await wrapper.vm.$nextTick()

    await wrapper.find('.submit-btn').trigger('click')

    expect(openSubmitDialog).toHaveBeenCalledTimes(1)
  })

  it('does not open the Submit dialog while the guest is not ready', async () => {
    const { wrapper } = await mountShellAt('/')

    await wrapper.find('.submit-btn').trigger('click')

    expect(openSubmitDialog).not.toHaveBeenCalled()
  })

  it('says it is still checking when no health snapshot has arrived yet', async () => {
    const { wrapper, store } = await mountShellAt('/')
    store.health = undefined
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.submit-wrapper').attributes('aria-label')).toBe('checking guest status…')
  })
})
