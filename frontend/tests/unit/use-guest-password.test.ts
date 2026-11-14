import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { failed, succeeded } from './annotation-fixtures'

const api = vi.hoisted(() => ({ guestsPassword: vi.fn() }))
vi.mock('@/api', () => api)

const { useGuestPassword } = await import('@/composables/use-guest-password')

const SECRET = 'made-up-Kd3-secret'

function start(name = 'lab1') {
  const guestName = ref(name)
  const password = effectScope().run(() => useGuestPassword(() => guestName.value))!
  return { password, guestName }
}

function pendingRequest() {
  let settle: (answer: unknown) => void = () => undefined
  api.guestsPassword.mockReturnValueOnce(new Promise((resolve) => (settle = resolve)))
  return (answer: unknown) => settle(answer)
}

beforeEach(() => {
  api.guestsPassword.mockReset().mockResolvedValue(succeeded({ password: SECRET }))
})

describe('useGuestPassword', () => {
  it('asks for nothing until it is told to', () => {
    const { password } = start()
    expect(api.guestsPassword).not.toHaveBeenCalled()
    expect(password.value.value).toBeUndefined()
    expect(password.revealed.value).toBe(false)
  })

  it('fetches the password of the guest once when toggled on, and holds it', async () => {
    const { password } = start('lab1')
    await password.toggle()
    expect(api.guestsPassword).toHaveBeenCalledTimes(1)
    expect(api.guestsPassword).toHaveBeenCalledWith(expect.objectContaining({ path: { name: 'lab1' } }))
    expect(password.value.value).toBe(SECRET)
    expect(password.revealed.value).toBe(true)
  })

  it('forgets the password when toggled off, and fetches it again the next time', async () => {
    const { password } = start()
    await password.toggle()
    await password.toggle()
    expect(password.value.value).toBeUndefined()
    expect(password.revealed.value).toBe(false)
    await password.toggle()
    expect(api.guestsPassword).toHaveBeenCalledTimes(2)
    expect(password.value.value).toBe(SECRET)
  })

  it('forgets the password when the card is for another guest', async () => {
    const { password, guestName } = start('lab1')
    await password.toggle()
    guestName.value = 'lab2'
    await nextTick()
    expect(password.value.value).toBeUndefined()
  })

  it('is busy while the request runs, and a second request waits for it', async () => {
    const answer = pendingRequest()
    const { password } = start()
    const first = password.toggle()
    expect(password.busy.value).toBe(true)
    expect(password.revealing.value).toBe(true)
    await password.toggle()
    await password.valueToCopy()
    expect(api.guestsPassword).toHaveBeenCalledTimes(1)
    answer(succeeded({ password: SECRET }))
    await first
    expect(password.busy.value).toBe(false)
    expect(password.revealing.value).toBe(false)
    expect(password.value.value).toBe(SECRET)
  })

  it('says why it could not get the password, and stays hidden', async () => {
    api.guestsPassword.mockResolvedValue(failed('The guest control service is not reachable', 502))
    const { password } = start()
    await password.toggle()
    expect(password.error.value).toBe('The guest control service is not reachable')
    expect(password.value.value).toBeUndefined()
    expect(password.revealed.value).toBe(false)
    expect(password.busy.value).toBe(false)
  })

  it('shows the failure on the card instead of as a toast', async () => {
    api.guestsPassword.mockResolvedValue(failed('no guest called lab1', 404))
    const { password } = start()
    await password.toggle()
    const { meta } = api.guestsPassword.mock.calls[0]![0] as { meta: { quietStatuses: number[] } }
    expect(meta.quietStatuses).toEqual(expect.arrayContaining([404, 502]))
  })

  it('drops the old error when it tries again', async () => {
    api.guestsPassword.mockResolvedValueOnce(failed('down', 502))
    const { password } = start()
    await password.toggle()
    await password.toggle()
    await flushPromises()
    expect(password.error.value).toBeUndefined()
    expect(password.value.value).toBe(SECRET)
  })

  describe('valueToCopy', () => {
    it('fetches the password for a copy without revealing it', async () => {
      const { password } = start()
      expect(await password.valueToCopy()).toBe(SECRET)
      expect(api.guestsPassword).toHaveBeenCalledTimes(1)
      expect(password.value.value).toBeUndefined()
      expect(password.revealed.value).toBe(false)
    })

    it('gives the revealed password without a request', async () => {
      const { password } = start()
      await password.toggle()
      expect(await password.valueToCopy()).toBe(SECRET)
      expect(api.guestsPassword).toHaveBeenCalledTimes(1)
    })

    it('gives nothing and says why when the fetch failed', async () => {
      api.guestsPassword.mockResolvedValue(failed('down', 502))
      const { password } = start()
      expect(await password.valueToCopy()).toBeUndefined()
      expect(password.error.value).toBe('down')
    })

    it('is busy, but is not revealing, while it fetches', async () => {
      const answer = pendingRequest()
      const { password } = start()
      const copying = password.valueToCopy()
      expect(password.busy.value).toBe(true)
      expect(password.revealing.value).toBe(false)
      answer(succeeded({ password: SECRET }))
      await copying
      expect(password.busy.value).toBe(false)
    })
  })
})
