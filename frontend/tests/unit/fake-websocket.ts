/** A WebSocket whose far end the test plays: `serverOpens`, `serverSends`, `serverCloses`. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static readonly OPEN = 1

  onopen: (() => void) | null = null
  onclose: ((event?: { code: number }) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  readyState = 0
  sent: unknown[] = []

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this)
  }

  static reset(): void {
    FakeWebSocket.instances = []
  }

  static get latest(): FakeWebSocket {
    return FakeWebSocket.instances.at(-1)!
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data))
  }

  close(): void {
    if (this.readyState === 3) return
    this.readyState = 3
    this.onclose?.({ code: 1005 })
  }

  serverOpens(): void {
    this.readyState = 1
    this.onopen?.()
  }

  serverSends(type: string, data: unknown, ts = '2026-10-13T15:40:00.000Z'): void {
    this.onmessage?.({ data: JSON.stringify({ type, ts, data }) })
  }

  serverCloses(code: number): void {
    this.readyState = 3
    this.onclose?.({ code })
  }

  get subscribes(): unknown[] {
    return this.sent.filter((message) => (message as { type: string }).type === 'subscribe')
  }
}

export function fakeSocketFactory(): (url: string) => WebSocket {
  return (url) => new FakeWebSocket(url) as unknown as WebSocket
}
