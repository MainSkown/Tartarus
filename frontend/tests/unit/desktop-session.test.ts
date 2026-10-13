import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DesktopPhase } from '@/services/desktop-close'
import type { GuacamoleModule } from '@/services/desktop-guacamole'
import { DesktopSession } from '@/services/desktop-session'
import { FakeDesktopSocket, TUNNEL_UUID } from './fake-desktop-socket'
import { FakeClient, FakeKeyboard, FakeMouse, fakeGuacamole, resetFakeGuacamole } from './fake-guacamole'

const ESC = 0xff1b
const KEY_A = 0x61
const MOUSE_STATE = { x: 320, y: 200, left: true }

let guacamole: GuacamoleModule
let panel: HTMLElement
let stage: HTMLElement
let phases: { phase: DesktopPhase; reason: string }[]
let clock: number

function makeSession(): DesktopSession {
  return new DesktopSession({
    guacamole,
    url: 'ws://tartarus.test/ws/analyses/7/desktop',
    panel,
    stage,
    socketFactory: (url) => new FakeDesktopSocket(url, 'guacamole') as unknown as WebSocket,
    now: () => clock,
    onChange: (state) => phases.push(state),
  })
}

function connectToGuest(): DesktopSession {
  const session = makeSession()
  session.connect()
  FakeDesktopSocket.latest.serverOpens()
  FakeDesktopSocket.latest.serverSends(TUNNEL_UUID)
  FakeClient.latest.firstFrame()
  return session
}

const lastPhase = () => phases.at(-1)?.phase

beforeEach(async () => {
  vi.useFakeTimers()
  FakeDesktopSocket.reset()
  resetFakeGuacamole()
  guacamole = await fakeGuacamole()
  panel = document.createElement('div')
  panel.tabIndex = 0
  stage = document.createElement('div')
  panel.append(stage)
  document.body.append(panel)
  phases = []
  clock = 10_000
})

afterEach(() => {
  panel.remove()
  vi.useRealTimers()
})

describe('DesktopSession connecting', () => {
  it('starts connecting and opens the socket it was given', () => {
    makeSession().connect()
    expect(lastPhase()).toBe('connecting')
    expect(FakeDesktopSocket.latest.url).toBe('ws://tartarus.test/ws/analyses/7/desktop')
  })

  it('waits for the guest once the tunnel is open but no picture has come', () => {
    makeSession().connect()
    FakeDesktopSocket.latest.serverOpens()
    FakeDesktopSocket.latest.serverSends(TUNNEL_UUID)
    expect(lastPhase()).toBe('waiting')
  })

  it('is connected at the first frame and shows the display in the stage', () => {
    connectToGuest()
    expect(lastPhase()).toBe('connected')
    expect(stage.contains(FakeClient.latest.display.element)).toBe(true)
  })
})

describe('DesktopSession mouse', () => {
  it('forwards the pointer over the display to the guest in display units', () => {
    connectToGuest()
    FakeMouse.latest.move(MOUSE_STATE)
    expect(FakeClient.latest.mouseStates).toEqual([[MOUSE_STATE, true]])
  })

  it('draws the guest cursor only, hiding the browser\'s over the display', () => {
    connectToGuest()
    expect(FakeClient.latest.display.element.style.cursor).toBe('none')
  })

  it('hides the guest cursor when the pointer leaves the display and shows it on the next move', () => {
    connectToGuest()
    FakeMouse.latest.leave()
    FakeMouse.latest.move(MOUSE_STATE)
    expect(FakeClient.latest.display.cursorShown).toEqual([false, true])
  })

  it('listens on the display itself, not on the page', () => {
    connectToGuest()
    expect(FakeMouse.latest.element).toBe(FakeClient.latest.display.element)
  })
})

describe('DesktopSession keyboard', () => {
  it('sends no key to the guest until the panel is captured', () => {
    connectToGuest()
    FakeKeyboard.latest.press(KEY_A)
    expect(FakeClient.latest.keyEvents).toEqual([])
  })

  it('sends keys while captured and keeps the browser from acting on them', () => {
    const session = connectToGuest()
    session.capture()
    expect(FakeKeyboard.latest.press(KEY_A)).toBe(false)
    FakeKeyboard.latest.release(KEY_A)
    expect(FakeClient.latest.keyEvents).toEqual([
      [1, KEY_A],
      [0, KEY_A],
    ])
  })

  it('stops sending after the panel is released, and lets go of what is held', () => {
    const session = connectToGuest()
    session.capture()
    FakeKeyboard.latest.press(KEY_A)
    session.release()
    expect(FakeClient.latest.keyEvents).toEqual([
      [1, KEY_A],
      [0, KEY_A],
    ])
    FakeKeyboard.latest.press(0x62)
    expect(FakeClient.latest.keyEvents).toHaveLength(2)
  })

  it('leaves keys to the browser while there is no picture yet', () => {
    const session = makeSession()
    session.connect()
    session.capture()
    expect(FakeKeyboard.latest.press(KEY_A)).toBe(true)
    expect(FakeClient.latest.keyEvents).toEqual([])
  })

  it('releases every held key when the window loses focus', () => {
    const session = connectToGuest()
    session.capture()
    FakeKeyboard.latest.press(KEY_A)
    window.dispatchEvent(new Event('blur'))
    expect(FakeClient.latest.keyEvents.at(-1)).toEqual([0, KEY_A])
  })

  it('takes two quick Escapes as a request to leave the panel', async () => {
    const session = connectToGuest()
    session.capture()
    panel.focus()
    FakeKeyboard.latest.press(ESC)
    FakeKeyboard.latest.release(ESC)
    clock += 200
    FakeKeyboard.latest.press(ESC)
    await Promise.resolve()
    expect(document.activeElement).not.toBe(panel)
    expect(FakeClient.latest.keyEvents.filter(([pressed, keysym]) => pressed === 1 && keysym === ESC)).toHaveLength(1)
  })

  it('keeps the focus when the second Escape is slow', () => {
    const session = connectToGuest()
    session.capture()
    panel.focus()
    FakeKeyboard.latest.press(ESC)
    FakeKeyboard.latest.release(ESC)
    clock += 900
    FakeKeyboard.latest.press(ESC)
    expect(document.activeElement).toBe(panel)
  })

  it('keeps the focus when another key came between the two Escapes', () => {
    const session = connectToGuest()
    session.capture()
    panel.focus()
    FakeKeyboard.latest.press(ESC)
    FakeKeyboard.latest.release(ESC)
    FakeKeyboard.latest.press(KEY_A)
    FakeKeyboard.latest.release(KEY_A)
    clock += 100
    FakeKeyboard.latest.press(ESC)
    expect(document.activeElement).toBe(panel)
  })
})

describe('DesktopSession with the real keyboard', () => {
  // The real Keyboard arms its key-repeat timer after onkeydown returns, so a release made inside
  // onkeydown leaves a repeat that calls the handler it just cleared.
  async function connectWithRealKeyboard(): Promise<DesktopSession> {
    const real = ((await import('guacamole-common-js')) as unknown as { default: GuacamoleModule }).default
    guacamole = { ...guacamole, Keyboard: real.Keyboard } as GuacamoleModule
    const session = connectToGuest()
    session.capture()
    panel.focus()
    return session
  }

  function type(eventType: 'keydown' | 'keyup', key: string, keyCode: number): void {
    panel.dispatchEvent(new KeyboardEvent(eventType, { key, code: key, keyCode, bubbles: true, cancelable: true }))
  }

  it('leaves the panel on two quick Escapes without a key repeating afterwards', async () => {
    await connectWithRealKeyboard()
    type('keydown', 'Escape', 27)
    type('keyup', 'Escape', 27)
    clock += 150
    type('keydown', 'Escape', 27)
    await Promise.resolve()
    expect(() => vi.advanceTimersByTime(2000)).not.toThrow()
    expect(document.activeElement).not.toBe(panel)
    type('keyup', 'Escape', 27)
    const sent = FakeClient.latest.keyEvents.length
    vi.advanceTimersByTime(2000)
    expect(FakeClient.latest.keyEvents).toHaveLength(sent)
  })

  it('lets go of a held key without a repeat when the panel is released', async () => {
    const session = await connectWithRealKeyboard()
    type('keydown', 'F1', 112)
    session.release()
    expect(() => vi.advanceTimersByTime(2000)).not.toThrow()
    expect(FakeClient.latest.keyEvents.filter(([pressed]) => pressed === 1)).toHaveLength(1)
  })
})

describe('DesktopSession buttons', () => {
  it('sends Ctrl+Alt+Delete as three presses and three releases, in order', () => {
    const session = connectToGuest()
    session.sendCtrlAltDel()
    expect(FakeClient.latest.keyEvents).toEqual([
      [1, 0xffe3],
      [1, 0xffe9],
      [1, 0xffff],
      [0, 0xffff],
      [0, 0xffe9],
      [0, 0xffe3],
    ])
  })

  it('sends nothing before there is a picture', () => {
    const session = makeSession()
    session.connect()
    session.sendCtrlAltDel()
    expect(FakeClient.latest.keyEvents).toEqual([])
  })
})

describe('DesktopSession scale', () => {
  it('fits the guest into the room it is given', () => {
    const session = connectToGuest()
    session.fit({ width: 640, height: 400 })
    expect(FakeClient.latest.display.scales.at(-1)).toBeCloseTo(0.5)
  })

  it('fits again when the guest resizes', () => {
    const session = connectToGuest()
    session.fit({ width: 640, height: 400 })
    FakeClient.latest.display.resizeGuest(1920, 1200)
    expect(FakeClient.latest.display.scales.at(-1)).toBeCloseTo(1 / 3)
  })

  it('leaves the scale alone for a stage with no size', () => {
    const session = connectToGuest()
    session.fit({ width: 0, height: 0 })
    expect(FakeClient.latest.display.scales).toEqual([])
  })

  it('applies the last room it was given once the display exists', () => {
    const session = makeSession()
    session.fit({ width: 640, height: 400 })
    session.connect()
    expect(FakeClient.latest.display.scales.at(-1)).toBeCloseTo(0.5)
  })
})

describe('DesktopSession closes', () => {
  it.each([
    [4408, 'desktop not available yet', 'timeout'],
    [4409, 'analysis is not running', 'not-running'],
    [1011, 'desktop service unavailable', 'unreachable'],
    [1002, 'malformed instruction', 'failed'],
  ] as const)('maps the server closing with %i to %s, keeping the reason', (code, reason, phase) => {
    makeSession().connect()
    FakeDesktopSocket.latest.serverOpens()
    FakeDesktopSocket.latest.serverCloses(code, reason)
    expect(phases.at(-1)).toEqual({ phase, reason })
  })

  it('reads a normal close with a prose reason as the end of the desktop once it was shown', () => {
    connectToGuest()
    FakeDesktopSocket.latest.serverCloses(1000, 'analysis is no longer running')
    expect(phases.at(-1)).toEqual({ phase: 'ended', reason: 'analysis is no longer running' })
  })

  it('reads guacd reporting an error before any picture as a desktop that is not there', () => {
    makeSession().connect()
    FakeDesktopSocket.latest.serverOpens()
    FakeDesktopSocket.latest.serverSends(TUNNEL_UUID)
    FakeClient.latest.guacdError('Unable to connect to VNC server')
    expect(phases.at(-1)).toEqual({ phase: 'unavailable', reason: 'Unable to connect to VNC server' })
  })

  it('keeps the first verdict when the server close follows guacd\'s error', () => {
    makeSession().connect()
    FakeDesktopSocket.latest.serverOpens()
    FakeDesktopSocket.latest.serverSends(TUNNEL_UUID)
    FakeClient.latest.guacdError('Unable to connect to VNC server')
    const seen = phases.length
    FakeDesktopSocket.latest.serverCloses(1000, 'desktop reported an error')
    expect(phases).toHaveLength(seen)
  })

  it('removes the display from the stage and lets go of the keyboard when the tunnel closes', () => {
    const session = connectToGuest()
    session.capture()
    FakeKeyboard.latest.press(KEY_A)
    FakeDesktopSocket.latest.serverCloses(1000, 'analysis is no longer running')
    expect(stage.contains(FakeClient.latest.display.element)).toBe(false)
    expect(FakeKeyboard.latest.resets).toBeGreaterThan(0)
  })
})

describe('DesktopSession disconnect', () => {
  it('closes the client and the socket and reports nothing more', () => {
    const session = connectToGuest()
    const seen = phases.length
    session.disconnect()
    expect(FakeClient.latest.disconnected).toBe(1)
    expect(FakeDesktopSocket.latest.closedWith?.code).toBe(1000)
    FakeDesktopSocket.latest.onclose?.({ code: 1005, reason: '' })
    expect(phases).toHaveLength(seen)
  })

  it('removes the display and stops listening to the window', () => {
    const session = connectToGuest()
    session.capture()
    session.disconnect()
    const resets = FakeKeyboard.latest.resets
    window.dispatchEvent(new Event('blur'))
    expect(FakeKeyboard.latest.resets).toBe(resets)
    expect(stage.contains(FakeClient.latest.display.element)).toBe(false)
  })

  it('is safe to call twice and before connecting', () => {
    const session = makeSession()
    session.disconnect()
    session.connect()
    session.disconnect()
    session.disconnect()
    expect(FakeClient.latest.disconnected).toBe(1)
  })

  it('stops the keyboard from reaching the guest', () => {
    const session = connectToGuest()
    session.capture()
    session.disconnect()
    FakeKeyboard.latest.press(KEY_A)
    expect(FakeClient.latest.keyEvents).toEqual([])
  })
})

describe('DesktopSession clipboard', () => {
  it('never opens a clipboard stream or touches the system clipboard', () => {
    const read = vi.fn()
    const write = vi.fn()
    Object.defineProperty(navigator, 'clipboard', { value: { readText: read, writeText: write }, configurable: true })
    const session = connectToGuest()
    session.capture()
    FakeKeyboard.latest.press(0x76)
    panel.dispatchEvent(new Event('paste'))
    session.sendCtrlAltDel()
    expect(FakeClient.latest.clipboardStreams).toBe(0)
    expect(read).not.toHaveBeenCalled()
    expect(write).not.toHaveBeenCalled()
  })
})
