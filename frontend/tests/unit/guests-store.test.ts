import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Guest } from '@/api'
import { failed, succeeded } from './annotation-fixtures'

const guestsListMock = vi.fn()
const guestsProfilesMock = vi.fn()
const guestsMediaMock = vi.fn()
vi.mock('@/api', () => ({
  guestsList: (...args: unknown[]) => guestsListMock(...args),
  guestsProfiles: (...args: unknown[]) => guestsProfilesMock(...args),
  guestsMedia: (...args: unknown[]) => guestsMediaMock(...args),
}))

const { useGuestsStore } = await import('@/stores/guests')

function guest(name: string, state: Guest['state'] = 'ready', badges: string[] = []): Guest {
  return { name, state, badges } as Guest
}

const GUESTS = [guest('win'), guest('lab1', 'ready', ['DEFENDER ON']), guest('lab3', 'building'), guest('lab4', 'failed')]

beforeEach(() => {
  setActivePinia(createPinia())
  guestsListMock.mockReset().mockResolvedValue(succeeded(GUESTS))
  guestsProfilesMock.mockReset().mockResolvedValue(succeeded([{ id: 'windows' }]))
  guestsMediaMock.mockReset().mockResolvedValue(succeeded([]))
})

describe('guests store', () => {
  it('lists the guests and keeps the ready ones apart', async () => {
    const store = useGuestsStore()
    await store.load()
    expect(store.guests.map((g) => g.name)).toEqual(['win', 'lab1', 'lab3', 'lab4'])
    expect(store.readyGuests.map((g) => g.name)).toEqual(['win', 'lab1'])
    expect(store.loadError).toBeUndefined()
  })

  it('finds a guest by name', async () => {
    const store = useGuestsStore()
    await store.load()
    expect(store.byName('lab1')?.badges).toEqual(['DEFENDER ON'])
    expect(store.byName('nosuch')).toBeUndefined()
  })

  it('defaults to the setting when that guest is ready', async () => {
    const store = useGuestsStore()
    await store.load()
    expect(store.defaultGuestName('lab1')).toBe('lab1')
  })

  it.each([['lab3'], ['lab4'], ['nosuch'], [null], [undefined]])(
    'falls back to the first ready guest when the setting is %s',
    async (setting) => {
      const store = useGuestsStore()
      await store.load()
      expect(store.defaultGuestName(setting)).toBe('win')
    },
  )

  it('has no default when no guest is ready', async () => {
    guestsListMock.mockResolvedValue(succeeded([guest('lab3', 'building')]))
    const store = useGuestsStore()
    await store.load()
    expect(store.defaultGuestName('lab3')).toBeUndefined()
  })

  it('keeps what it had and says why when a later read fails', async () => {
    const store = useGuestsStore()
    await store.load()
    guestsListMock.mockResolvedValue(failed('control down', 502))
    await store.load()
    expect(store.guests).toHaveLength(4)
    expect(store.loadError).toBeDefined()
  })

  it('loads the profiles on request', async () => {
    const store = useGuestsStore()
    await store.loadProfiles()
    expect(store.profiles.map((p) => p.id)).toEqual(['windows'])
  })

  it('knows the packages a guest accepts through its profile', async () => {
    guestsListMock.mockResolvedValue(succeeded([{ name: 'win', state: 'ready', profile: 'windows' }]))
    guestsProfilesMock.mockResolvedValue(succeeded([{ id: 'windows', packages: ['exe', 'dll'] }]))
    const store = useGuestsStore()
    await Promise.all([store.load(), store.loadProfiles()])
    expect(store.packagesOf('win')).toEqual(['exe', 'dll'])
    expect(store.packagesOf('nosuch')).toEqual([])
  })

  it('names the edition a guest was built from through the media it came from', async () => {
    const media = [
      { file: 'w.iso', variants: [{ index: 4, name: 'Windows 11 Education' }, { index: 5, name: 'Windows 11 Pro' }] },
    ]
    guestsMediaMock.mockResolvedValue(succeeded(media))
    const store = useGuestsStore()
    await store.loadMedia()
    const built = { name: 'a', media: { file: 'w.iso', variant: '5' } } as Guest
    expect(store.editionName(built)).toBe('Windows 11 Pro')
    expect(store.editionName({ name: 'b', media: { file: 'gone.iso', variant: '5' } } as Guest)).toBeUndefined()
    expect(store.editionName({ name: 'c', media: { file: 'w.iso', variant: '9' } } as Guest)).toBeUndefined()
    expect(store.editionName({ name: 'd' } as Guest)).toBeUndefined()
  })
})
