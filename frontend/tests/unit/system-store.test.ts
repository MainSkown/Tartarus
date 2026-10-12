import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HealthMessage, HealthStatus, SystemHealth } from '@/api'

const REST_HEALTH: SystemHealth = {
  postgres: { status: 'ok', message: null },
  opensearch: { status: 'ok', message: null },
  cape: { status: 'down', message: 'not set up yet' },
  guest: { status: 'down', message: 'not set up yet' },
}

const systemHealthMock = vi.fn()
vi.mock('@/api', () => ({
  systemHealth: (...args: unknown[]) => systemHealthMock(...args),
}))

type FakeState = 'connecting' | 'open' | 'reconnecting' | 'closed'
const wsState = ref<FakeState>('connecting')
let pushHealth: ((message: HealthMessage) => void) | undefined
const connect = vi.fn()
const disconnect = vi.fn()
const subscribe = vi.fn((handler: (message: HealthMessage) => void) => {
  pushHealth = handler
  return () => {
    pushHealth = undefined
  }
})

vi.mock('@/services/ws', () => ({
  createSystemHealthClient: () => ({
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

  it('exposes guest readiness and message for the Submit button', async () => {
    const store = useSystemStore()
    await vi.waitFor(() => expect(store.health).toBeDefined())
    expect(store.guestReady).toBe(false)
    expect(store.guestMessage).toBe('not set up yet')

    pushMessage({ ...REST_HEALTH, guest: { status: 'ok', message: null } })
    expect(store.guestReady).toBe(true)
    store.$dispose()
  })
})
