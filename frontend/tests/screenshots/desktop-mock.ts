import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { expect, type Page } from '@playwright/test'

const GUEST = { width: 1280, height: 800 }
const FRAME_FILE = path.resolve(fileURLToPath(new URL('.', import.meta.url)), 'data', 'shot-1.jpg')
const BLOB_CHUNK = 8192
const SRC = 12
const TUNNEL_UUID = '5d0a1c76-9f4a-4a4e-a2b4-0f4f0d3e1c11'
const PING_PREFIX = '0.,4.ping,'

export function instruction(opcode: string, ...args: (string | number)[]): string {
  return [opcode, ...args.map(String)].map((element) => `${element.length}.${element}`).join(',') + ';'
}

/** What guacd sends for one full screen: its size, the picture as an image stream, and the sync that ends the frame. */
export function frameInstructions(jpeg: Buffer = readFileSync(FRAME_FILE)): string[] {
  const base64 = jpeg.toString('base64')
  const chunks = base64.match(new RegExp(`.{1,${BLOB_CHUNK}}`, 'g')) ?? []
  return [
    instruction('size', 0, GUEST.width, GUEST.height),
    instruction('img', 1, SRC, 0, 'image/jpeg', 0, 0),
    ...chunks.map((chunk) => instruction('blob', 1, chunk)),
    instruction('end', 1),
    instruction('sync', Date.now()),
  ]
}

export interface DesktopSocketMock {
  /** Resolves once the page has opened its `n`th desktop connection. */
  connected(n?: number): Promise<void>
  /** The tunnel's first internal instruction, which the server sends once it has admitted the analysis. */
  admit(): void
  /** The guest's screen, as guacd would draw it. */
  sendFrame(): void
  send(...instructions: string[]): void
  close(code: number, reason: string): void
  /** The instructions the page sent, without the tunnel's own pings. */
  fromBrowser(): string[]
  connections(): number
}

/** Mocks `WS /ws/analyses/{id}/desktop`; the test plays the server and guacd. */
export function mockDesktopSocket(page: Page, analysisId: number): Promise<DesktopSocketMock> {
  return mockDesktopSocketAt(page, `/ws/analyses/${analysisId}/desktop`)
}

/** The same mock for any desktop path, such as a guest build's `/ws/guests/{name}/desktop`. */
export async function mockDesktopSocketAt(page: Page, pathname: string): Promise<DesktopSocketMock> {
  const sockets: { send(message: string): void; close(options: { code: number; reason: string }): void }[] = []
  const received: string[] = []

  await page.routeWebSocket((url) => url.pathname === pathname, (ws) => {
    sockets.push(ws)
    ws.onMessage((message) => {
      const text = String(message)
      if (text.startsWith(PING_PREFIX)) ws.send(text)
      else received.push(text)
    })
  })

  const newest = () => sockets[sockets.length - 1]!
  const mock: DesktopSocketMock = {
    async connected(n = 1) {
      await expect.poll(() => sockets.length, { message: `waiting for desktop connection ${n}` }).toBeGreaterThanOrEqual(n)
    },
    admit: () => newest().send(instruction('', TUNNEL_UUID)),
    sendFrame: () => mock.send(...frameInstructions()),
    send(...instructions) {
      for (const text of instructions) newest().send(text)
    },
    close: (code, reason) => newest().close({ code, reason }),
    fromBrowser: () => [...received],
    connections: () => sockets.length,
  }
  return mock
}
