import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HealthStatus, JobProgress, QueueSnapshot, SystemHealth } from '@/api'
import type { SystemMessage } from '@/services/ws'

const REST_HEALTH: SystemHealth = {
  postgres: { status: 'ok', message: null },
  opensearch: { status: 'ok', message: null },
  cape: { status: 'down', message: 'not set up yet' },
  guest: { status: 'down', message: 'not set up yet' },
}

const systemHealthMock = vi.fn()
vi.mock('@/api', () => ({
  systemQueue: () => Promise.resolve({ data: undefined }),
  systemHealth: (...args: unknown[]) => systemHealthMock(...args),
}))

type FakeState = 'connecting' | 'open' | 'reconnecting' | 'closed'
const wsState = ref<FakeState>('connecting')
let pushHealth: ((message: SystemMessage) => void) | undefined
const connect = vi.fn()
const disconnect = vi.fn()
const subscribe = vi.fn((handler: (message: SystemMessage) => void) => {
  pushHealth = handler
  return () => {
    pushHealth = undefined
  }
})

vi.mock('@/services/ws', () => ({
  createSystemClient: () => ({
    state: wsState,
    lastMessage: ref(undefined),
    subscribe,
    connect,
    disconnect,
  }),
}))

const { useSystemStore } = await import('@/stores/system')

function pushMessage(data: SystemHealth): void {
  pushHealth?.({ type: 'health', ts: '2026-10-12T00:00:00Z', data })
}

const JOB: JobProgress = {
  id: 3,
  type: 'export_report',
  analysis_id: 193,
  status: 'running',
  step: 'Rendering the PDF',
  progress: 45,
  result: null,
}

beforeEach(() => {
  setActivePinia(createPinia())
  systemHealthMock.mockReset().mockResolvedValue({ data: REST_HEALTH })
  wsState.value = 'connecting'
  pushHealth = undefined
  connect.mockClear()
  disconnect.mockClear()
})

describe('useSystemStore', () => {
  it('populates health from the REST fallback on creation', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toEqual(REST_HEALTH))
    expect(systemHealthMock).toHaveBeenCalledOnce()
    store.$dispose()
  })

  it('connects the WS client so pushes keep the REST snapshot live', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toBeDefined())
    expect(connect).toHaveBeenCalledOnce()

    const pushed: SystemHealth = { ...REST_HEALTH, cape: { status: 'ok', message: null } }
    pushMessage(pushed)
    expect(store.health).toEqual(pushed)
    store.$dispose()
  })

  it('exposes the WS connection state', () => {
    const store = useSystemStore()
    expect(store.connectionState).toBe('connecting')
    wsState.value = 'reconnecting'
    expect(store.connectionState).toBe('reconnecting')
    store.$dispose()
  })

  it('disconnects the WS client and unsubscribes when disposed', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toBeDefined())
    store.$dispose()
    expect(disconnect).toHaveBeenCalledOnce()
    pushMessage({ ...REST_HEALTH, cape: { status: 'ok', message: null } })
    // The subscription was torn down, so a push after disposal must not resurrect state.
    expect(store.health).toEqual(REST_HEALTH)
  })

  const storeStatusCases: Array<[HealthStatus, HealthStatus, HealthStatus]> = [
    ['ok', 'ok', 'ok'],
    ['ok', 'degraded', 'degraded'],
    ['degraded', 'ok', 'degraded'],
    ['ok', 'down', 'down'],
    ['degraded', 'down', 'down'],
    ['down', 'down', 'down'],
  ]

  it.each(storeStatusCases)(
    'storeStatus of postgres=%s + opensearch=%s is the worse one: %s',
    async (postgres, opensearch, expected) => {
      const store = useSystemStore()
      await vi.waitFor(() => expect(store.health).toBeDefined())
      pushMessage({
        ...REST_HEALTH,
        postgres: { status: postgres, message: null },
        opensearch: { status: opensearch, message: null },
      })
      expect(store.storeStatus).toBe(expected)
      store.$dispose()
    },
  )

  it('hands queue pushes to whoever registered with onQueue, not to the health snapshot', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toBeDefined())
    const received: QueueSnapshot[] = []
    store.onQueue((snapshot) => received.push(snapshot))

    const snapshot: QueueSnapshot = { running: [], queued_count: 2, queued: [] }
    pushHealth?.({ type: 'queue', ts: '2026-10-21T10:00:00Z', data: snapshot })

    expect(received).toEqual([snapshot])
    expect(store.health).toEqual(REST_HEALTH)
    store.$dispose()
  })

  it('exposes guest readiness and message for the Submit button', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toBeDefined())
    expect(store.guestReady).toBe(false)
    expect(store.guestMessage).toBe('not set up yet')

    pushMessage({ ...REST_HEALTH, guest: { status: 'ok', message: null } })
    expect(store.guestReady).toBe(true)
    store.$dispose()
  })

  it('counts a degraded guest status as ready: some guest is not ready, another is', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toBeDefined())

    pushMessage({ ...REST_HEALTH, guest: { status: 'degraded', message: 'lab4 is building' } })
    expect(store.guestReady).toBe(true)
    expect(store.guestMessage).toBe('lab4 is building')

    pushMessage({ ...REST_HEALTH, guest: { status: 'down', message: 'no guest is ready' } })
    expect(store.guestReady).toBe(false)
    store.$dispose()
  })

  it('hands job pushes to the job handlers and keeps them out of the health snapshot', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toEqual(REST_HEALTH))
    const received: JobProgress[] = []
    store.onJob((job) => received.push(job))

    pushHealth?.({ type: 'job', job: JOB })

    expect(received).toEqual([JOB])
    expect(store.health).toEqual(REST_HEALTH)
    store.$dispose()
  })

  it('stops calling a job handler that unsubscribed', async () => {
    const store = useSystemStore()
    const received: JobProgress[] = []
    const unsubscribe = store.onJob((job) => received.push(job))
    unsubscribe()

    pushHealth?.({ type: 'job', job: JOB })

    expect(received).toEqual([])
    store.$dispose()
  })
})
