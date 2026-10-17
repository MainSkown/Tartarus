import { createPinia, setActivePinia } from 'pinia'
import { nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Guest, GuestProfile } from '@/api'
import { failed, succeeded } from './annotation-fixtures'

const guestsListMock = vi.fn()
const guestsProfilesMock = vi.fn()
vi.mock('@/api', () => ({
  guestsList: (...args: unknown[]) => guestsListMock(...args),
  guestsProfiles: (...args: unknown[]) => guestsProfilesMock(...args),
}))

const { useGuestChoice, FALLBACK_PACKAGES } = await import('@/composables/use-guest-choice')
const { useGuestsStore } = await import('@/stores/guests')

function guest(name: string, state: Guest['state'], profile: string, badges: string[] = []): Guest {
  return { name, state, profile, badges } as Guest
}

function profile(id: string, displayName: string, packages: string[]): GuestProfile {
  return { id, display_name: displayName, packages } as GuestProfile
}

const GUESTS = [
  guest('lab1', 'ready', 'windows', ['DEFENDER ON']),
  guest('lab2', 'ready', 'windows', ['DEFENDER OFF']),
  guest('lab3', 'building', 'windows'),
  guest('lab4', 'failed', 'ubuntu'),
]
const PROFILES = [profile('windows', 'Windows 11', ['exe', 'dll', 'doc']), profile('ubuntu', 'Ubuntu 24.04', ['bash', 'elf'])]

async function loaded(setting: string | null | undefined = undefined) {
  const defaultGuest = ref(setting)
  const choice = useGuestChoice(defaultGuest)
  await choice.load()
  return { choice, defaultGuest }
}

beforeEach(() => {
  setActivePinia(createPinia())
  guestsListMock.mockReset().mockResolvedValue(succeeded(GUESTS))
  guestsProfilesMock.mockReset().mockResolvedValue(succeeded(PROFILES))
})

describe('useGuestChoice', () => {
  describe('the guest list', () => {
    it('lists every guest with its badges and profile name, in the store order', async () => {
      const { choice } = await loaded()
      expect(choice.guestOptions.value.map((option) => [option.name, option.badges, option.profileName])).toEqual([
        ['lab1', ['DEFENDER ON'], 'Windows 11'],
        ['lab2', ['DEFENDER OFF'], 'Windows 11'],
        ['lab3', [], 'Windows 11'],
        ['lab4', [], 'Ubuntu 24.04'],
      ])
    })

    it('disables a guest that is not ready and gives its state as the reason', async () => {
      const { choice } = await loaded()
      expect(choice.guestOptions.value.map((option) => [option.name, option.disabled, option.reason])).toEqual([
        ['lab1', false, undefined],
        ['lab2', false, undefined],
        ['lab3', true, 'building'],
        ['lab4', true, 'failed'],
      ])
    })

    it('loads the guests and the profiles together', async () => {
      await loaded()
      expect(guestsListMock).toHaveBeenCalledTimes(1)
      expect(guestsProfilesMock).toHaveBeenCalledTimes(1)
    })
  })

  describe('the chosen guest', () => {
    it('is the Settings default when that guest is ready', async () => {
      const { choice } = await loaded('lab2')
      expect(choice.guestName.value).toBe('lab2')
    })

    it.each([['lab3'], ['gone'], [null], [undefined]])('falls back to the first ready guest for the setting %s', async (setting) => {
      const { choice } = await loaded(setting)
      expect(choice.guestName.value).toBe('lab1')
    })

    it('follows the setting when it arrives after the guests', async () => {
      const { choice, defaultGuest } = await loaded()
      defaultGuest.value = 'lab2'
      expect(choice.guestName.value).toBe('lab2')
    })

    it('keeps what the analyst picked over the setting', async () => {
      const { choice, defaultGuest } = await loaded('lab1')
      choice.guestName.value = 'lab2'
      defaultGuest.value = 'lab1'
      expect(choice.guestName.value).toBe('lab2')
    })

    it('is nothing while no guest is ready', async () => {
      guestsListMock.mockResolvedValue(succeeded([guest('lab3', 'building', 'windows')]))
      const { choice } = await loaded()
      expect(choice.guestName.value).toBeUndefined()
      expect(choice.chosenOption.value).toBeUndefined()
    })

    it('has its option, to show what was chosen', async () => {
      const { choice } = await loaded('lab2')
      expect(choice.chosenOption.value).toMatchObject({ name: 'lab2', badges: ['DEFENDER OFF'], profileName: 'Windows 11' })
    })
  })

  describe('the package', () => {
    it('offers auto and the chosen guest profile packages', async () => {
      const { choice } = await loaded('lab1')
      expect(choice.packageOptions.value).toEqual(['auto', 'exe', 'dll', 'doc'])
    })

    it('follows the guest the analyst switches to', async () => {
      guestsListMock.mockResolvedValue(succeeded([guest('lab1', 'ready', 'windows'), guest('lab5', 'ready', 'ubuntu')]))
      const { choice } = await loaded('lab1')
      choice.guestName.value = 'lab5'
      expect(choice.packageOptions.value).toEqual(['auto', 'bash', 'elf'])
    })

    it('offers the static list only while the profiles have not loaded', async () => {
      guestsProfilesMock.mockResolvedValue(failed('down', 502))
      const { choice } = await loaded('lab1')
      expect(choice.packageOptions.value).toEqual(['auto', ...FALLBACK_PACKAGES])
    })

    it('offers only auto when a loaded profile has no package', async () => {
      guestsProfilesMock.mockResolvedValue(succeeded([profile('windows', 'Windows 11', [])]))
      const { choice } = await loaded('lab1')
      expect(choice.packageOptions.value).toEqual(['auto'])
    })

    it('resets to auto when the chosen guest does not accept the selected package', async () => {
      guestsListMock.mockResolvedValue(succeeded([guest('lab1', 'ready', 'windows'), guest('lab5', 'ready', 'ubuntu')]))
      const { choice } = await loaded('lab1')
      choice.packageName.value = 'doc'

      choice.guestName.value = 'lab5'
      await nextTick()

      expect(choice.packageName.value).toBe('auto')
    })

    it('keeps the package when the new guest accepts it too', async () => {
      guestsListMock.mockResolvedValue(succeeded([guest('lab1', 'ready', 'windows'), guest('lab6', 'ready', 'windows')]))
      const { choice } = await loaded('lab1')
      choice.packageName.value = 'doc'

      choice.guestName.value = 'lab6'
      await nextTick()

      expect(choice.packageName.value).toBe('doc')
    })
  })

  describe('when no guest is ready', () => {
    it('says why for each guest', async () => {
      guestsListMock.mockResolvedValue(succeeded([guest('lab3', 'building', 'windows'), guest('lab4', 'failed', 'ubuntu')]))
      const { choice } = await loaded()
      expect(choice.noGuestReason.value).toBe('No guest is ready: lab3 is building, lab4 is failed')
    })

    it('says so when there is no guest at all', async () => {
      guestsListMock.mockResolvedValue(succeeded([]))
      const { choice } = await loaded()
      expect(choice.noGuestReason.value).toBe('No guest is ready: none has been built')
    })

    it('is silent while a guest is ready', async () => {
      const { choice } = await loaded()
      expect(choice.noGuestReason.value).toBeUndefined()
    })

    it('is silent before the list has loaded', () => {
      const choice = useGuestChoice(ref(undefined))
      expect(choice.noGuestReason.value).toBeUndefined()
    })
  })

  describe('when the list cannot be loaded', () => {
    beforeEach(() => {
      guestsListMock.mockResolvedValue(failed('guest control is down', 502))
    })

    it('reports the list as unavailable and gives no reason that blocks submitting', async () => {
      const { choice } = await loaded()
      expect(choice.listUnavailable.value).toBe(true)
      expect(choice.noGuestReason.value).toBeUndefined()
    })

    it('sends no guest, leaving the backend to pick', async () => {
      const { choice } = await loaded()
      expect(choice.optionPayload.value).toEqual({})
    })
  })

  describe('the options payload', () => {
    it('holds the chosen guest', async () => {
      const { choice } = await loaded('lab2')
      expect(choice.optionPayload.value).toEqual({ guest: 'lab2' })
    })

    it('adds the package unless it is auto', async () => {
      const { choice } = await loaded('lab1')
      choice.packageName.value = 'dll'
      expect(choice.optionPayload.value).toEqual({ guest: 'lab1', package: 'dll' })
    })

    it('reads the store the Guest page shares', async () => {
      const { choice } = await loaded()
      expect(choice.guestOptions.value).toHaveLength(useGuestsStore().guests.length)
    })
  })
})
