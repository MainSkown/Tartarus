import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeDesktopSocket, TUNNEL_UUID } from './fake-desktop-socket'
import { FakeClient, resetFakeGuacamole } from './fake-guacamole'

const loadGuacamole = vi.hoisted(() => vi.fn())

vi.mock('@/services/desktop-guacamole', () => ({ loadGuacamole }))

const { fakeGuacamole } = await import('./fake-guacamole')
const DesktopPanel = (await import('@/components/DesktopPanel.vue')).default

const mounted: ReturnType<typeof mount>[] = []

async function mountPanel(props: Record<string, unknown> = {}) {
  const wrapper = mount(DesktopPanel, {
    attachTo: document.body,
    global: { plugins: [Quasar] },
    props: { path: '/ws/guests/lab4/desktop', wanted: true, subject: 'build', ...props },
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

const socket = () => FakeDesktopSocket.latest
const message = (wrapper: ReturnType<typeof mount>) => wrapper.find('[data-desktop="message"]')

beforeEach(() => {
  FakeDesktopSocket.reset()
  resetFakeGuacamole()
  loadGuacamole.mockImplementation(() => fakeGuacamole())
  vi.stubGlobal('WebSocket', FakeDesktopSocket)
})

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('DesktopPanel for the desktop of a guest build', () => {
  it('opens the socket of the path it was given', async () => {
    await mountPanel()
    await vi.waitFor(() => expect(FakeDesktopSocket.instances).toHaveLength(1))
    expect(socket().url).toContain('/ws/guests/lab4/desktop')
    expect(socket().protocols).toBe('guacamole')
  })

  it('says it is connecting, then shows the screen without a message', async () => {
    const wrapper = await mountPanel()
    expect(message(wrapper).text()).toContain('connecting to the desktop')
    socket().serverOpens()
    socket().serverSends(TUNNEL_UUID)
    FakeClient.latest.firstFrame()
    await flushPromises()
    expect(message(wrapper).exists()).toBe(false)
  })

  it('shows the reason of a desktop that is not there yet (4408) with a RETRY that connects again', async () => {
    const wrapper = await mountPanel()
    socket().serverOpens()
    socket().serverCloses(4408, 'desktop not available yet')
    await flushPromises()
    expect(message(wrapper).text()).toContain('desktop not available yet')
    await wrapper.find('[data-desktop="retry"]').trigger('click')
    await flushPromises()
    expect(FakeDesktopSocket.instances).toHaveLength(2)
  })

  it('says the build no longer shows a desktop when the tunnel closes normally after the picture (1000)', async () => {
    const wrapper = await mountPanel()
    socket().serverOpens()
    socket().serverSends(TUNNEL_UUID)
    FakeClient.latest.firstFrame()
    await flushPromises()
    socket().serverCloses(1000, 'build is no longer at a desktop step')
    await flushPromises()
    expect(message(wrapper).text()).toContain('The build no longer shows a desktop.')
    expect(message(wrapper).text()).not.toContain('analysis')
    expect(wrapper.find('[data-desktop="retry"]').exists()).toBe(false)
  })

  it('says the desktop belongs to a build step when the build is not at one (4409)', async () => {
    const wrapper = await mountPanel()
    socket().serverOpens()
    socket().serverCloses(4409, 'no desktop')
    await flushPromises()
    expect(message(wrapper).text()).toContain('only available while the build is at a step that shows one')
  })

  it('says the desktop service is unreachable on 1011 and the connection was lost on any other close', async () => {
    const wrapper = await mountPanel()
    socket().serverOpens()
    socket().serverCloses(1011, 'down')
    await flushPromises()
    expect(message(wrapper).text()).toContain('unreachable')
    await wrapper.find('[data-desktop="retry"]').trigger('click')
    await flushPromises()
    socket().serverOpens()
    socket().serverCloses(1006, '')
    await flushPromises()
    expect(message(wrapper).text()).toContain('connection was lost')
  })

  it('does not connect while what it belongs to has no desktop', async () => {
    await mountPanel({ wanted: false })
    expect(FakeDesktopSocket.instances).toHaveLength(0)
  })

  it('has no clipboard control: only fullscreen and Ctrl+Alt+Del', async () => {
    const wrapper = await mountPanel()
    const labels = wrapper.findAll('.desktop-toolbar button').map((button) => button.text())
    expect(labels.join(' ')).not.toMatch(/clipboard|paste|copy/i)
    expect(labels).toHaveLength(2)
  })

  it('has its title and its two buttons in the one shared panel header, the hint under the screen', async () => {
    const wrapper = await mountPanel()
    const header = wrapper.find('.pane-heading')
    expect(header.find('.pane-heading__title').text()).toBe('DESKTOP')
    expect(header.find('.pane-heading__actions').findAll('button').map((button) => button.text())).toEqual([expect.stringContaining('[FULLSCREEN]'), expect.stringContaining('[CTRL+ALT+DEL]')])
    expect(wrapper.find('[data-desktop="screen"] button').exists()).toBe(false)
    expect(wrapper.find('[data-desktop="toolbar-note"]').exists()).toBe(true)
    expect(header.find('[data-desktop="toolbar-note"]').exists()).toBe(false)
  })

  it('is boxed like the live tab’s other panels unless its owner says it sits among plain sections', async () => {
    expect((await mountPanel()).classes()).toContain('live-desktop--framed')
    expect((await mountPanel({ bare: true })).classes()).not.toContain('live-desktop--framed')
  })
})
