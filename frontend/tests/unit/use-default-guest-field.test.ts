import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Guest } from '@/api'
import { failed, succeeded } from './annotation-fixtures'

const guestsListMock = vi.fn()
vi.mock('@/api', () => ({
  guestsList: (...args: unknown[]) => guestsListMock(...args),
  guestsProfiles: vi.fn(),
}))

const { useDefaultGuestField } = await import('@/composables/use-default-guest-field')

function guest(name: string, state: Guest['state']): Guest {
  return { name, state } as Guest
}

async function loaded(stored: string | null | undefined) {
  const field = useDefaultGuestField(ref(stored))
  await field.load()
  return field
}

beforeEach(() => {
  setActivePinia(createPinia())
  guestsListMock.mockReset().mockResolvedValue(succeeded([guest('lab1', 'ready'), guest('lab2', 'ready'), guest('lab3', 'building')]))
})

describe('useDefaultGuestField', () => {
  it('offers the first ready guest, meaning null, and then each ready guest', async () => {
    const field = await loaded(null)
    expect(field.options.value).toEqual([
      { label: 'first ready guest', value: null },
      { label: 'lab1', value: 'lab1' },
      { label: 'lab2', value: 'lab2' },
    ])
  })

  it('has no note while the stored name is a ready guest, or none is stored', async () => {
    expect((await loaded('lab2')).note.value).toBeUndefined()
    expect((await loaded(null)).note.value).toBeUndefined()
    expect((await loaded(undefined)).note.value).toBeUndefined()
  })

  it('says a stored guest that no longer exists is replaced by the first ready guest', async () => {
    expect((await loaded('lab9')).note.value).toBe('lab9 no longer exists: the first ready guest is used')
  })

  it('says a stored guest that is not ready is replaced by the first ready guest', async () => {
    expect((await loaded('lab3')).note.value).toBe('lab3 is building: the first ready guest is used')
  })

  it('shows the stored name as it is, since it is not among the options', async () => {
    expect((await loaded('lab9')).displayValue.value).toBe('lab9')
    expect((await loaded('lab2')).displayValue.value).toBeUndefined()
  })

  it('cannot judge the stored name when the guests did not load, so it says nothing', async () => {
    guestsListMock.mockResolvedValue(failed('guest control is down', 502))
    const field = await loaded('lab9')
    expect(field.note.value).toBeUndefined()
    expect(field.options.value).toEqual([{ label: 'first ready guest', value: null }])
  })
})
