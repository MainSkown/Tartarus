import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DesktopTunnel } from '@/services/desktop-tunnel'
import { loadGuacamole, type GuacamoleModule } from '@/services/desktop-guacamole'
import { FakeDesktopSocket, instruction, TUNNEL_UUID } from './fake-desktop-socket'

let guacamole: GuacamoleModule

function makeTunnel() {
  const tunnel = new DesktopTunnel(guacamole, 'ws://tartarus.test/ws/analyses/7/desktop', (url) => {
    return new FakeDesktopSocket(url, 'guacamole') as unknown as WebSocket
  })
  const closes: { code: number; reason: string }[] = []
  const instructions: [string, string[]][] = []
  tunnel.onclose = (code, reason) => closes.push({ code, reason })
  tunnel.oninstruction = (opcode, args) => instructions.push([opcode, args.map(String)])
  return { tunnel, closes, instructions }
}

function openTunnel() {
  const made = makeTunnel()
  made.tunnel.connect()
  FakeDesktopSocket.latest.serverOpens()
  FakeDesktopSocket.latest.serverSends(TUNNEL_UUID)
  return made
}

beforeEach(async () => {
  vi.useFakeTimers()
  FakeDesktopSocket.reset()
  guacamole = await loadGuacamole()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('DesktopTunnel', () => {
  it('connects the guacamole subprotocol socket to the url as given', () => {
    const { tunnel } = makeTunnel()
    tunnel.connect()
    expect(FakeDesktopSocket.latest.url).toBe('ws://tartarus.test/ws/analyses/7/desktop')
    expect(FakeDesktopSocket.latest.protocols).toBe('guacamole')
    expect(tunnel.state).toBe(guacamole.Tunnel.State.CONNECTING)
  })

  it('opens on the first internal instruction and keeps its uuid', () => {
    const { tunnel, instructions } = openTunnel()
    expect(tunnel.state).toBe(guacamole.Tunnel.State.OPEN)
    expect(tunnel.uuid).toBe('5d0a1c76-9f4a-4a4e-a2b4-0f4f0d3e1c11')
    expect(instructions).toEqual([])
  })

  it('hands every other instruction to the client, one per frame', () => {
    const { instructions } = openTunnel()
    FakeDesktopSocket.latest.serverSends(instruction('size', 0, 1280, 800), instruction('sync', 1234))
    expect(instructions).toEqual([
      ['size', ['0', '1280', '800']],
      ['sync', ['1234']],
    ])
  })

  it('writes an instruction the way the protocol counts it', () => {
    const { tunnel } = openTunnel()
    tunnel.sendMessage('mouse', 640, 400, 1)
    expect(FakeDesktopSocket.latest.sent.at(-1)).toBe('5.mouse,3.640,3.400,1.1;')
  })

  it('does not send before it is open', () => {
    const { tunnel } = makeTunnel()
    tunnel.connect()
    tunnel.sendMessage('nop')
    expect(FakeDesktopSocket.latest.sent).toEqual([])
  })

  it('reports the close code and the reason as the server gave them, never a parsed number', () => {
    const { closes } = openTunnel()
    FakeDesktopSocket.latest.serverCloses(4408, 'desktop not available yet')
    expect(closes).toEqual([{ code: 4408, reason: 'desktop not available yet' }])
  })

  it('reports a normal close that has a prose reason as code 1000', () => {
    const { tunnel, closes } = openTunnel()
    FakeDesktopSocket.latest.serverCloses(1000, 'analysis is no longer running')
    expect(closes).toEqual([{ code: 1000, reason: 'analysis is no longer running' }])
    expect(tunnel.state).toBe(guacamole.Tunnel.State.CLOSED)
  })

  it('does not call onerror for a server close: the code is the whole story', () => {
    const { tunnel } = openTunnel()
    const onerror = vi.fn()
    tunnel.onerror = onerror
    FakeDesktopSocket.latest.serverCloses(1000, 'analysis is no longer running')
    expect(onerror).not.toHaveBeenCalled()
  })

  it('answers its own disconnect silently and closes the socket normally', () => {
    const { tunnel, closes } = openTunnel()
    tunnel.disconnect()
    expect(FakeDesktopSocket.latest.closedWith?.code).toBe(1000)
    FakeDesktopSocket.latest.onclose?.({ code: 1005, reason: '' })
    expect(closes).toEqual([])
    expect(tunnel.state).toBe(guacamole.Tunnel.State.CLOSED)
  })

  it('pings every half second and keeps going as the server echoes', () => {
    openTunnel()
    const socket = FakeDesktopSocket.latest
    const pings = () => socket.sent.filter((frame) => frame.startsWith('0.,4.ping,'))
    vi.advanceTimersByTime(500)
    expect(pings()).toHaveLength(1)
    socket.serverSends(socket.sent.at(-1)!)
    vi.advanceTimersByTime(500)
    expect(pings()).toHaveLength(2)
    socket.serverSends(socket.sent.at(-1)!)
    vi.advanceTimersByTime(500)
    expect(pings()).toHaveLength(3)
  })

  it('stays open past the receive timeout while echoes keep arriving', () => {
    const { tunnel, closes } = openTunnel()
    const socket = FakeDesktopSocket.latest
    for (let second = 0; second < 40; second += 0.5) {
      vi.advanceTimersByTime(500)
      socket.serverSends(socket.sent.at(-1)!)
    }
    expect(tunnel.isConnected()).toBe(true)
    expect(closes).toEqual([])
  })

  it('gives up with an abnormal close when nothing arrives for the receive timeout', () => {
    const { tunnel, closes } = openTunnel()
    vi.advanceTimersByTime(tunnel.receiveTimeout + 1)
    expect(closes).toEqual([{ code: 1006, reason: 'no data from the server' }])
    expect(FakeDesktopSocket.latest.closedWith?.code).toBe(1000)
  })

  it('goes unstable after a quiet moment and recovers on the next frame', () => {
    const { tunnel } = openTunnel()
    vi.advanceTimersByTime(tunnel.unstableThreshold + 1)
    expect(tunnel.state).toBe(guacamole.Tunnel.State.UNSTABLE)
    FakeDesktopSocket.latest.serverSends(instruction('nop'))
    expect(tunnel.state).toBe(guacamole.Tunnel.State.OPEN)
  })

  it('closes with a protocol error when a frame cannot be parsed', () => {
    const { closes } = openTunnel()
    FakeDesktopSocket.latest.serverSends('x.nonsense;')
    expect(closes).toEqual([{ code: 1002, reason: 'malformed instruction from the server' }])
  })

  it('stops pinging once closed', () => {
    const { tunnel } = openTunnel()
    tunnel.disconnect()
    const before = FakeDesktopSocket.latest.sent.length
    vi.advanceTimersByTime(5000)
    expect(FakeDesktopSocket.latest.sent).toHaveLength(before)
  })
})
