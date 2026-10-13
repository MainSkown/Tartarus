/** A WebSocket for the desktop tunnel: text frames in and out, the far end played by the test. */
export class FakeDesktopSocket {
  static instances: FakeDesktopSocket[] = []

  onopen: (() => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  readyState = 0
  sent: string[] = []
  closedWith: { code?: number; reason?: string } | undefined

  constructor(
    readonly url: string,
    readonly protocols?: string | string[],
  ) {
    FakeDesktopSocket.instances.push(this)
  }

  static reset(): void {
    FakeDesktopSocket.instances = []
  }

  static get latest(): FakeDesktopSocket {
    return FakeDesktopSocket.instances.at(-1)!
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(code?: number, reason?: string): void {
    if (this.readyState === 3) return
    this.readyState = 3
    this.closedWith = { code, reason }
  }

  serverOpens(): void {
    this.readyState = 1
    this.onopen?.()
  }

  serverSends(...instructions: string[]): void {
    for (const instruction of instructions) this.onmessage?.({ data: instruction })
  }

  serverCloses(code: number, reason = ''): void {
    this.readyState = 3
    this.onclose?.({ code, reason })
  }
}

export function instruction(opcode: string, ...args: (string | number)[]): string {
  return [opcode, ...args.map(String)].map((element) => `${element.length}.${element}`).join(',') + ';'
}

export const TUNNEL_UUID = instruction('', '5d0a1c76-9f4a-4a4e-a2b4-0f4f0d3e1c11')
