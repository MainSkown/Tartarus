import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisRead, AnalysisStatus } from '@/api'
import { analysisWithStatus } from './analysis-fixtures'
import { ARTIFACTS_VIEW } from './detections-fixtures'
import { FakeDesktopSocket, TUNNEL_UUID } from './fake-desktop-socket'
import { FakeClient, FakeKeyboard, FakeMouse, resetFakeGuacamole } from './fake-guacamole'

const loadGuacamole = vi.hoisted(() => vi.fn())

vi.mock('@/services/desktop-guacamole', () => ({ loadGuacamole }))
vi.mock('@/api', () => ({ viewsArtifacts: vi.fn() }))

const { viewsArtifacts } = await import('@/api')
const { fakeGuacamole } = await import('./fake-guacamole')
const LiveDesktopSlot = (await import('@/components/LiveDesktopSlot.vue')).default

const ESC = 0xff1b
const interactive = (status: AnalysisStatus = 'running', overrides: Partial<AnalysisRead> = {}) =>
  analysisWithStatus(status, { id: 45, options: { interactive: true }, ...overrides })

const mounted: ReturnType<typeof mount>[] = []

async function mountSlot(analysis: AnalysisRead = interactive()) {
  const wrapper = mount(LiveDesktopSlot, { attachTo: document.body, global: { plugins: [Quasar] }, props: { analysis } })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

async function connectToGuest(analysis?: AnalysisRead) {
  const wrapper = await mountSlot(analysis)
  FakeDesktopSocket.latest.serverOpens()
  FakeDesktopSocket.latest.serverSends(TUNNEL_UUID)
  FakeClient.latest.firstFrame()
  await flushPromises()
  return wrapper
}

const socket = () => FakeDesktopSocket.latest
const message = (wrapper: ReturnType<typeof mount>) => wrapper.find('[data-desktop="message"]')
const screen = (wrapper: ReturnType<typeof mount>) => wrapper.find('[data-desktop="screen"]')

beforeEach(() => {
  FakeDesktopSocket.reset()
  resetFakeGuacamole()
  loadGuacamole.mockImplementation(() => fakeGuacamole())
  vi.stubGlobal('WebSocket', FakeDesktopSocket)
  vi.mocked(viewsArtifacts).mockResolvedValue({ data: ARTIFACTS_VIEW, error: undefined } as never)
})

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('LiveDesktopSlot', () => {
  it('is the desktop of the live tab, headed DESKTOP', async () => {
    const wrapper = await mountSlot()
    expect(wrapper.attributes('data-live')).toBe('desktop')
    expect(wrapper.find('.pane-heading__title').text()).toBe('DESKTOP')
  })

  it('opens the desktop socket of its analysis', async () => {
    await mountSlot(interactive('running', { id: 45 }))
    expect(socket().url).toContain('/ws/analyses/45/desktop')
    expect(socket().protocols).toBe('guacamole')
  })

  it('says it is connecting, then that it waits for the guest', async () => {
    const wrapper = await mountSlot()
    expect(message(wrapper).text()).toContain('connecting to the desktop')
    socket().serverOpens()
    socket().serverSends(TUNNEL_UUID)
    await flushPromises()
    expect(message(wrapper).text()).toContain('waiting for the guest to start')
  })

  it('shows the guest screen without a message once the first frame is there', async () => {
    const wrapper = await connectToGuest()
    expect(message(wrapper).exists()).toBe(false)
    expect(screen(wrapper).element.contains(FakeClient.latest.display.element)).toBe(true)
  })
})

describe('LiveDesktopSlot when the server closes the socket', () => {
  it('shows the reason of a desktop that is not there yet, with a RETRY that connects again', async () => {
    const wrapper = await mountSlot()
    socket().serverOpens()
    socket().serverCloses(4408, 'desktop not available yet')
    await flushPromises()
    expect(message(wrapper).text()).toContain('desktop not available yet')
    await wrapper.find('[data-desktop="retry"]').trigger('click')
    await flushPromises()
    expect(FakeDesktopSocket.instances).toHaveLength(2)
    expect(message(wrapper).text()).toContain('connecting to the desktop')
  })

  it('says the desktop service is unreachable on 1011, with RETRY', async () => {
    const wrapper = await mountSlot()
    socket().serverOpens()
    socket().serverCloses(1011, 'desktop service unavailable')
    await flushPromises()
    expect(message(wrapper).text()).toContain('unreachable')
    expect(wrapper.find('[data-desktop="retry"]').text()).toContain('RETRY')
  })

  it('says the run has ended, with no button, when the desktop closes normally after it was shown', async () => {
    const wrapper = await connectToGuest()
    socket().serverCloses(1000, 'analysis is no longer running')
    await flushPromises()
    expect(message(wrapper).text()).toContain('The run has ended. CAPE is processing the results.')
    expect(message(wrapper).text()).not.toContain('analysis is no longer running')
    expect(message(wrapper).text()).not.toContain('NaN')
    expect(wrapper.find('[data-desktop="retry"]').exists()).toBe(false)
  })

  it('says the run has ended when guacd reports the end of the run after the picture', async () => {
    const wrapper = await connectToGuest()
    FakeClient.latest.guacdError('Aborted. See logs.')
    await flushPromises()
    expect(message(wrapper).text()).toContain('The run has ended')
    expect(wrapper.find('[data-desktop="retry"]').exists()).toBe(false)
  })

  it('offers RECONNECT when the connection drops while the run goes on', async () => {
    const wrapper = await connectToGuest()
    socket().serverCloses(1006, '')
    await flushPromises()
    expect(message(wrapper).text()).toContain('the desktop connection was lost')
    expect(wrapper.find('[data-desktop="retry"]').text()).toContain('RECONNECT')
    await wrapper.find('[data-desktop="retry"]').trigger('click')
    await flushPromises()
    expect(FakeDesktopSocket.instances).toHaveLength(2)
  })

  it('says the run has ended, not that the connection dropped, when END RUN was pressed', async () => {
    const wrapper = await connectToGuest()
    await wrapper.setProps({ endRequested: true })
    socket().serverCloses(1006, '')
    await flushPromises()
    expect(message(wrapper).text()).toContain('The run has ended')
    expect(wrapper.find('[data-desktop="retry"]').exists()).toBe(false)
  })

  it('says the guest is not running when guacd reports an error before any picture', async () => {
    const wrapper = await mountSlot()
    socket().serverOpens()
    socket().serverSends(TUNNEL_UUID)
    FakeClient.latest.guacdError('Unable to connect to VNC server')
    await flushPromises()
    expect(message(wrapper).text()).toContain('the guest is not running')
    expect(wrapper.find('[data-desktop="retry"]').exists()).toBe(true)
  })

  it('says the desktop only exists while the analysis runs on 4409, with no button', async () => {
    const wrapper = await mountSlot()
    socket().serverOpens()
    socket().serverCloses(4409, 'analysis is not running')
    await flushPromises()
    expect(message(wrapper).text()).toContain('only available while the analysis runs')
    expect(wrapper.find('[data-desktop="retry"]').exists()).toBe(false)
  })
})

describe('LiveDesktopSlot when the library cannot start', () => {
  it('says the connection failed, with RECONNECT, instead of leaving the panel blank', async () => {
    loadGuacamole.mockRejectedValue(new Error('Failed to fetch dynamically imported module'))
    const wrapper = await mountSlot()
    expect(message(wrapper).text()).toContain('the desktop connection was lost')
    expect(message(wrapper).text()).toContain('Failed to fetch dynamically imported module')
    expect(wrapper.find('[data-desktop="retry"]').text()).toContain('RECONNECT')
  })
})

describe('LiveDesktopSlot by analysis status', () => {
  it('does not load the library or open a socket while the analysis is queued', async () => {
    const wrapper = await mountSlot(interactive('queued'))
    expect(loadGuacamole).not.toHaveBeenCalled()
    expect(FakeDesktopSocket.instances).toHaveLength(0)
    expect(message(wrapper).text()).toContain('only available while the analysis runs')
  })

  it('connects once the queued analysis starts', async () => {
    const wrapper = await mountSlot(interactive('queued'))
    await wrapper.setProps({ analysis: interactive('starting') })
    await flushPromises()
    expect(FakeDesktopSocket.instances).toHaveLength(1)
  })

  it('connects for a starting analysis, whose desktop appears when the guest is up', async () => {
    await mountSlot(interactive('starting'))
    expect(FakeDesktopSocket.instances).toHaveLength(1)
  })

  it('drops the connection when the analysis stops running', async () => {
    const wrapper = await connectToGuest()
    await wrapper.setProps({ analysis: interactive('processing') })
    await flushPromises()
    expect(FakeClient.latest.disconnected).toBe(1)
    expect(socket().closedWith?.code).toBe(1000)
    expect(message(wrapper).text()).toContain('The run has ended. CAPE is processing the results.')
    expect(message(wrapper).text()).not.toContain('only available while')
  })

  it('shows the last screenshot of a finished analysis instead of connecting', async () => {
    const wrapper = await mountSlot(interactive('done'))
    expect(FakeDesktopSocket.instances).toHaveLength(0)
    expect(wrapper.find('[data-desktop="last-screenshot"]').attributes('src')).toBe('/api/analyses/45/artifacts/screenshots/3')
    expect(message(wrapper).text()).toContain('The run has ended. CAPE is processing the results.')
  })

  it('keeps "only available while the analysis runs" for a run that never finished', async () => {
    const wrapper = await mountSlot(interactive('cancelled'))
    expect(message(wrapper).text()).toContain('only available while the analysis runs')
  })

  it('shows no screenshot for a run that left none', async () => {
    const wrapper = await mountSlot(interactive('failed'))
    expect(wrapper.find('[data-desktop="last-screenshot"]').exists()).toBe(false)
    expect(message(wrapper).text()).toContain('only available while the analysis runs')
  })
})

describe('LiveDesktopSlot keyboard', () => {
  it('sends keys only while the screen has focus', async () => {
    const wrapper = await connectToGuest()
    FakeKeyboard.latest.press(0x61)
    expect(FakeClient.latest.keyEvents).toEqual([])

    await screen(wrapper).trigger('focus')
    FakeKeyboard.latest.press(0x61)
    expect(FakeClient.latest.keyEvents).toEqual([[1, 0x61]])

    await screen(wrapper).trigger('blur')
    FakeKeyboard.latest.press(0x62)
    expect(FakeClient.latest.keyEvents).toEqual([
      [1, 0x61],
      [0, 0x61],
    ])
  })

  it('shows the capture on the screen only while focused with a picture', async () => {
    const wrapper = await connectToGuest()
    expect(screen(wrapper).attributes('data-captured')).toBe('false')
    await screen(wrapper).trigger('focus')
    expect(screen(wrapper).attributes('data-captured')).toBe('true')
    await screen(wrapper).trigger('blur')
    expect(screen(wrapper).attributes('data-captured')).toBe('false')
  })

  it('does not show a capture for a focused screen with no picture yet', async () => {
    const wrapper = await mountSlot()
    await screen(wrapper).trigger('focus')
    expect(screen(wrapper).attributes('data-captured')).toBe('false')
  })

  it('captures when the picture arrives while the screen already has focus', async () => {
    const wrapper = await mountSlot()
    ;(screen(wrapper).element as HTMLElement).focus()
    socket().serverOpens()
    socket().serverSends(TUNNEL_UUID)
    FakeClient.latest.firstFrame()
    await flushPromises()
    FakeKeyboard.latest.press(0x61)
    expect(FakeClient.latest.keyEvents).toEqual([[1, 0x61]])
  })

  it('releases the focus on two quick Escapes', async () => {
    const wrapper = await connectToGuest()
    const element = screen(wrapper).element as HTMLElement
    element.focus()
    await screen(wrapper).trigger('focus')
    FakeKeyboard.latest.press(ESC)
    FakeKeyboard.latest.release(ESC)
    FakeKeyboard.latest.press(ESC)
    await flushPromises()
    expect(document.activeElement).not.toBe(element)
    expect(screen(wrapper).attributes('data-captured')).toBe('false')
  })

  it('keeps the keys typed into the guest from reaching shortcuts elsewhere in the app', async () => {
    const wrapper = await connectToGuest()
    const reachedApp = vi.fn()
    document.addEventListener('keydown', reachedApp)
    await screen(wrapper).trigger('focus')
    await screen(wrapper).trigger('keydown', { key: 'a' })
    await screen(wrapper).trigger('blur')
    await screen(wrapper).trigger('keydown', { key: 'a' })
    document.removeEventListener('keydown', reachedApp)
    expect(reachedApp).toHaveBeenCalledTimes(1)
  })

  it('focuses the screen when it is clicked, since the guest mouse handling cancels the browser default', async () => {
    const wrapper = await connectToGuest()
    expect(document.activeElement).not.toBe(screen(wrapper).element)
    await screen(wrapper).trigger('mousedown')
    expect(document.activeElement).toBe(screen(wrapper).element)
  })

  it('forwards the mouse without needing focus', async () => {
    await connectToGuest()
    FakeMouse.latest.move({ x: 10, y: 20 })
    expect(FakeClient.latest.mouseStates).toHaveLength(1)
  })
})

describe('LiveDesktopSlot toolbar', () => {
  it('sends Ctrl+Alt+Delete from its button', async () => {
    const wrapper = await connectToGuest()
    await wrapper.find('[data-desktop="ctrl-alt-del"]').trigger('click')
    expect(FakeClient.latest.keyEvents.map(([pressed, keysym]) => `${pressed}:${keysym.toString(16)}`)).toEqual([
      '1:ffe3',
      '1:ffe9',
      '1:ffff',
      '0:ffff',
      '0:ffe9',
      '0:ffe3',
    ])
  })

  it('disables the guest buttons until there is a picture', async () => {
    const wrapper = await mountSlot()
    expect(wrapper.find('[data-desktop="ctrl-alt-del"]').attributes('disabled')).toBeDefined()
    FakeDesktopSocket.latest.serverOpens()
    FakeDesktopSocket.latest.serverSends(TUNNEL_UUID)
    FakeClient.latest.firstFrame()
    await flushPromises()
    expect(wrapper.find('[data-desktop="ctrl-alt-del"]').attributes('disabled')).toBeUndefined()
  })

  it('asks the browser to put the whole panel in fullscreen', async () => {
    const wrapper = await connectToGuest()
    const request = vi.fn(() => Promise.resolve())
    wrapper.element.requestFullscreen = request
    await wrapper.find('[data-desktop="fullscreen"]').trigger('click')
    expect(request).toHaveBeenCalledOnce()
  })

  it('says so when the browser refuses fullscreen', async () => {
    const wrapper = await connectToGuest()
    wrapper.element.requestFullscreen = vi.fn(() => Promise.reject(new TypeError('Fullscreen is blocked')))
    await wrapper.find('[data-desktop="fullscreen"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-desktop="toolbar-note"]').text()).toContain('fullscreen was refused: Fullscreen is blocked')
  })
})

describe('LiveDesktopSlot leaving', () => {
  it('disconnects the client, closes the socket and stops listening when unmounted', async () => {
    const wrapper = await connectToGuest()
    await screen(wrapper).trigger('focus')
    const resets = FakeKeyboard.latest.resets
    wrapper.unmount()
    mounted.splice(0)
    expect(FakeClient.latest.disconnected).toBe(1)
    expect(socket().closedWith?.code).toBe(1000)
    window.dispatchEvent(new Event('blur'))
    expect(FakeKeyboard.latest.resets).toBe(resets + 1)
  })

  it('does not open a socket when it is unmounted while the library is still loading', async () => {
    let release!: () => void
    loadGuacamole.mockImplementation(async () => {
      await new Promise<void>((resolve) => (release = resolve))
      return fakeGuacamole()
    })
    const wrapper = mount(LiveDesktopSlot, { attachTo: document.body, global: { plugins: [Quasar] }, props: { analysis: interactive() } })
    wrapper.unmount()
    release()
    await flushPromises()
    expect(FakeDesktopSocket.instances).toHaveLength(0)
  })
})
