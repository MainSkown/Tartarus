import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SystemHealth } from '@/api'

vi.mock('@/api', () => ({ systemHealth: vi.fn().mockResolvedValue({ data: undefined }) }))
vi.mock('@/services/ws', () => ({
  createSystemClient: () => ({
    state: { value: 'open' },
    lastMessage: { value: undefined },
    subscribe: () => () => undefined,
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const { useGuestBlockReason } = await import('@/services/guest-gate')
const { useSystemStore } = await import('@/stores/system')

function healthWithGuest(guest: SystemHealth['guest']): SystemHealth {
  const ok = { status: 'ok', message: null } as const
  return { postgres: ok, opensearch: ok, cape: ok, guest }
}

describe('useGuestBlockReason', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('says it is checking until the first health snapshot arrives', () => {
    expect(useGuestBlockReason().value).toBe('checking guest status…')
  })

  it("explains with the guest's own message while it is not ready", () => {
    useSystemStore().health = healthWithGuest({ status: 'down', message: 'guest VM is stopped' })
    expect(useGuestBlockReason().value).toBe('guest VM is stopped')
  })

  it('has no reason once the guest is ready', () => {
    useSystemStore().health = healthWithGuest({ status: 'ok', message: null })
    expect(useGuestBlockReason().value).toBeUndefined()
  })
})
