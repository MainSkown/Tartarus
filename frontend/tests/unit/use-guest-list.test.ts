import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import type { BuildView, Guest, JobProgress } from '@/api'
import type { SystemMessage } from '@/services/ws'
import { failed, succeeded } from './annotation-fixtures'

const api = vi.hoisted(() => ({
  guestsList: vi.fn(),
  guestsMedia: vi.fn(),
  guestsProfiles: vi.fn(),
  guestsReadBuild: vi.fn(),
  guestsActiveBuild: vi.fn(),
  guestsCheck: vi.fn(),
  guestsDelete: vi.fn(),
  guestsRetrySelftest: vi.fn(),
  settingsRead: vi.fn(),
  systemHealth: vi.fn(),
}))
const confirmDestructive = vi.hoisted(() => vi.fn())
let pushMessage: (message: SystemMessage) => void = () => undefined

vi.mock('@/api', () => api)
vi.mock('@/services/confirm', () => ({ confirmDestructive }))
vi.mock('@/services/ws', () => ({
  createSystemClient: () => ({
    state: { value: 'open' },
    subscribe: (handler: (message: SystemMessage) => void) => {
      pushMessage = handler
      return () => undefined
    },
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const { useGuestList, POLL_INTERVAL_MS } = await import('@/composables/use-guest-list')

function guest(name: string, overrides: Partial<Guest> = {}): Guest {
  return { name, state: 'ready', ...overrides }
}

function build(overrides: Partial<BuildView> = {}): BuildView {
  return { id: 'b1', guest: 'lab4', kind: 'clone', status: 'running', step: 2, steps: [], percent: 40, message: 'Cloning the disk', log: [], ...overrides } as BuildView
}

function jobMessage(type: JobProgress['type'], status: JobProgress['status'] = 'running'): SystemMessage {
  return { type: 'job', job: { id: 1, type, analysis_id: null, status, step: '', progress: 0, result: null } } as SystemMessage
}

let scope: EffectScope

function start() {
  scope = effectScope()
  return scope.run(() => useGuestList())!
}

const READY = [guest('win'), guest('lab1')]
const BUILDING = guest('lab4', { state: 'building', build_id: 'b1' })

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  Notify.create = vi.fn()
  api.systemHealth.mockResolvedValue({ data: undefined })
  api.guestsList.mockReset().mockResolvedValue(succeeded(READY))
  api.guestsMedia.mockReset().mockResolvedValue(succeeded([]))
  api.guestsProfiles.mockReset().mockResolvedValue(succeeded([{ id: 'windows', display_name: 'Windows' }]))
  api.guestsReadBuild.mockReset().mockResolvedValue(succeeded(build()))
  api.guestsActiveBuild.mockReset().mockResolvedValue(failed('no build', 404))
  api.guestsCheck.mockReset()
  api.guestsDelete.mockReset().mockResolvedValue({ data: undefined, error: undefined })
  api.guestsRetrySelftest.mockReset().mockResolvedValue(succeeded({ job_id: 3, build_id: 'b1', guest: 'lab1' }))
  api.settingsRead.mockReset().mockResolvedValue(succeeded({ default_guest: null }))
  confirmDestructive.mockReset().mockResolvedValue(true)
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
})

describe('useGuestList loading', () => {
  it('is loading until the first answer, then lists the guests', async () => {
    const list = start()
    expect(list.loading.value).toBe(true)
    await flushPromises()
    expect(list.loading.value).toBe(false)
    expect(list.guests.value.map((g) => g.name)).toEqual(['win', 'lab1'])
    expect(list.loadError.value).toBeUndefined()
  })

  it('also loads the profiles the cards name the OS from', async () => {
    const list = start()
    await flushPromises()
    expect(list.profileOf(guest('win', { profile: 'windows' }))?.display_name).toBe('Windows')
  })

  it('keeps the error of a failed load and loads again on reload', async () => {
    api.guestsList.mockResolvedValue(failed('guest control service is not reachable', 502))
    const list = start()
    await flushPromises()
    expect(list.loadError.value).toBe('guest control service is not reachable')
    expect(list.loading.value).toBe(false)

    api.guestsList.mockResolvedValue(succeeded(READY))
    await list.reload()
    expect(list.loadError.value).toBeUndefined()
    expect(list.guests.value).toHaveLength(2)
  })
})

describe('useGuestList default marker', () => {
  it('marks the guest of the Settings default', async () => {
    api.settingsRead.mockResolvedValue(succeeded({ default_guest: 'lab1' }))
    const list = start()
    await flushPromises()
    expect(list.defaultName.value).toBe('lab1')
  })

  it('marks the first ready guest when no default is set', async () => {
    api.guestsList.mockResolvedValue(succeeded([BUILDING, guest('lab1')]))
    const list = start()
    await flushPromises()
    expect(list.defaultName.value).toBe('lab1')
  })

  it('ignores a failing settings read', async () => {
    api.settingsRead.mockResolvedValue(failed('down', 502))
    const list = start()
    await flushPromises()
    expect(list.defaultName.value).toBe('win')
  })
})

describe('useGuestList staying fresh', () => {
  it('reloads when a guest_build job message arrives, whatever its status', async () => {
    start()
    await flushPromises()
    api.guestsList.mockClear()
    pushMessage(jobMessage('guest_build', 'done'))
    await flushPromises()
    expect(api.guestsList).toHaveBeenCalledTimes(1)
  })

  it('ignores the jobs of other types', async () => {
    start()
    await flushPromises()
    api.guestsList.mockClear()
    pushMessage(jobMessage('ingest'))
    await flushPromises()
    expect(api.guestsList).not.toHaveBeenCalled()
  })

  it('stops listening to jobs when the scope ends', async () => {
    start()
    await flushPromises()
    scope.stop()
    api.guestsList.mockClear()
    pushMessage(jobMessage('guest_build'))
    await flushPromises()
    expect(api.guestsList).not.toHaveBeenCalled()
  })

  it('does not poll while every guest is settled', async () => {
    start()
    await flushPromises()
    api.guestsList.mockClear()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    expect(api.guestsList).not.toHaveBeenCalled()
  })

  it('polls every 5 seconds while a guest is building, and stops once it is ready', async () => {
    expect(POLL_INTERVAL_MS).toBe(5_000)
    api.guestsList.mockResolvedValue(succeeded([BUILDING]))
    start()
    await flushPromises()
    api.guestsList.mockClear()

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(api.guestsList).toHaveBeenCalledTimes(1)

    api.guestsList.mockResolvedValue(succeeded([guest('lab4')]))
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(api.guestsList).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    expect(api.guestsList).toHaveBeenCalledTimes(2)
  })

  it('polls while a guest is testing', async () => {
    api.guestsList.mockResolvedValue(succeeded([guest('lab4', { state: 'testing' })]))
    start()
    await flushPromises()
    api.guestsList.mockClear()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(api.guestsList).toHaveBeenCalledTimes(1)
  })

  it('stops polling when the scope ends', async () => {
    api.guestsList.mockResolvedValue(succeeded([BUILDING]))
    start()
    await flushPromises()
    scope.stop()
    api.guestsList.mockClear()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
    expect(api.guestsList).not.toHaveBeenCalled()
  })

  it('does not start a second reload while one is in flight, but reloads once more after it', async () => {
    let finish: (value: unknown) => void = () => undefined
    const list = start()
    await flushPromises()
    api.guestsList.mockClear()
    api.guestsList.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)))
    const first = list.reload()
    void list.reload()
    void list.reload()
    expect(api.guestsList).toHaveBeenCalledTimes(1)
    finish(succeeded(READY))
    await first
    await flushPromises()
    expect(api.guestsList).toHaveBeenCalledTimes(2)
  })
})

describe('useGuestList builds', () => {
  it('reads the progress of a building guest by its build id', async () => {
    api.guestsList.mockResolvedValue(succeeded([BUILDING, guest('win')]))
    const list = start()
    await flushPromises()
    expect(api.guestsReadBuild).toHaveBeenCalledTimes(1)
    expect(api.guestsReadBuild.mock.calls[0]![0].path).toEqual({ build_id: 'b1' })
    expect(list.buildOf('lab4')?.percent).toBe(40)
    expect(list.buildOf('win')).toBeUndefined()
  })

  it('finds the build through the active build when the guest carries no build id', async () => {
    api.guestsList.mockResolvedValue(succeeded([guest('lab4', { state: 'testing' })]))
    api.guestsActiveBuild.mockResolvedValue(succeeded({ build_id: 'b9', guest: 'lab4', job_id: 3 }))
    const list = start()
    await flushPromises()
    expect(api.guestsReadBuild.mock.calls[0]![0].path).toEqual({ build_id: 'b9' })
    expect(list.buildOf('lab4')).toBeDefined()
  })

  it('forgets the progress of a guest that is no longer building', async () => {
    api.guestsList.mockResolvedValue(succeeded([BUILDING]))
    const list = start()
    await flushPromises()
    api.guestsList.mockResolvedValue(succeeded([guest('lab4')]))
    await list.reload()
    expect(list.buildOf('lab4')).toBeUndefined()
  })

  it('shows a building guest without progress when its build cannot be read', async () => {
    api.guestsList.mockResolvedValue(succeeded([BUILDING]))
    api.guestsReadBuild.mockResolvedValue(failed('no such build', 404))
    const list = start()
    await flushPromises()
    expect(list.guests.value).toHaveLength(1)
    expect(list.buildOf('lab4')).toBeUndefined()
  })
})

describe('useGuestList run checks', () => {
  const PROBES = [
    { id: 'agent', ok: true, message: 'agent answers' },
    { id: 'internet', ok: false, message: 'reached the internet' },
  ]

  it('is idle before and busy while the checks run, then holds the result', async () => {
    let answer: (value: unknown) => void = () => undefined
    api.guestsCheck.mockReturnValue(new Promise((resolve) => (answer = resolve)))
    const list = start()
    await flushPromises()
    expect(list.checkOf('win')).toBeUndefined()

    const running = list.runChecks('win')
    expect(list.checkOf('win')).toEqual({ busy: true })
    expect(api.guestsCheck.mock.calls[0]![0].path).toEqual({ name: 'win' })

    answer(succeeded({ name: 'win', checks: PROBES }))
    await running
    expect(list.checkOf('win')).toEqual({ busy: false, result: { name: 'win', checks: PROBES } })
  })

  it('keeps the checks of one guest apart from another', async () => {
    api.guestsCheck.mockResolvedValue(succeeded({ name: 'win', checks: PROBES }))
    const list = start()
    await flushPromises()
    await list.runChecks('win')
    expect(list.checkOf('lab1')).toBeUndefined()
  })

  it('shows the 409 reason inline, and asks the client not to toast it', async () => {
    api.guestsCheck.mockResolvedValue(failed('An analysis is running', 409))
    const list = start()
    await flushPromises()
    await list.runChecks('win')
    expect(list.checkOf('win')).toEqual({ busy: false, error: 'An analysis is running' })
    expect(api.guestsCheck.mock.calls[0]![0].meta).toEqual({ quietStatuses: expect.arrayContaining([409]) })
  })

  it('replaces an old result when the checks run again', async () => {
    api.guestsCheck.mockResolvedValueOnce(failed('An analysis is running', 409))
    api.guestsCheck.mockResolvedValueOnce(succeeded({ name: 'win', checks: PROBES }))
    const list = start()
    await flushPromises()
    await list.runChecks('win')
    await list.runChecks('win')
    expect(list.checkOf('win')?.error).toBeUndefined()
    expect(list.checkOf('win')?.result?.checks).toHaveLength(2)
  })

  it('does not start the checks twice while they run', async () => {
    api.guestsCheck.mockReturnValue(new Promise(() => undefined))
    const list = start()
    await flushPromises()
    void list.runChecks('win')
    void list.runChecks('win')
    expect(api.guestsCheck).toHaveBeenCalledTimes(1)
  })
})

describe('useGuestList delete', () => {
  it('asks first, naming the guest, and does nothing when the analyst declines', async () => {
    confirmDestructive.mockResolvedValue(false)
    const list = start()
    await flushPromises()
    await list.remove('lab1')
    expect(confirmDestructive.mock.calls[0]![0].title).toContain('lab1')
    expect(api.guestsDelete).not.toHaveBeenCalled()
  })

  it('deletes the confirmed guest, reloads the list and says so', async () => {
    const list = start()
    await flushPromises()
    api.guestsList.mockResolvedValue(succeeded([guest('win')]))
    await list.remove('lab1')
    expect(api.guestsDelete.mock.calls[0]![0].path).toEqual({ name: 'lab1' })
    expect(list.guests.value.map((g) => g.name)).toEqual(['win'])
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success', message: expect.stringContaining('lab1') }))
  })

  it('is busy while the delete runs', async () => {
    let answer: (value: unknown) => void = () => undefined
    api.guestsDelete.mockReturnValue(new Promise((resolve) => (answer = resolve)))
    const list = start()
    await flushPromises()
    const deleting = list.remove('lab1')
    await flushPromises()
    expect(list.isDeleting('lab1')).toBe(true)
    answer({ data: undefined, error: undefined })
    await deleting
    expect(list.isDeleting('lab1')).toBe(false)
  })

  it('shows a 409 message on the guest and keeps the guest', async () => {
    api.guestsDelete.mockResolvedValue(failed('lab1 is being built', 409))
    const list = start()
    await flushPromises()
    await list.remove('lab1')
    expect(list.deleteErrorOf('lab1')).toBe('lab1 is being built')
    expect(list.isDeleting('lab1')).toBe(false)
    expect(list.guests.value.map((g) => g.name)).toContain('lab1')
    expect(api.guestsDelete.mock.calls[0]![0].meta).toEqual({ quietStatuses: expect.arrayContaining([409]) })
  })

  it('clears the earlier refusal when the delete is tried again', async () => {
    api.guestsDelete.mockResolvedValueOnce(failed('lab1 is being built', 409))
    const list = start()
    await flushPromises()
    await list.remove('lab1')
    await list.remove('lab1')
    expect(list.deleteErrorOf('lab1')).toBeUndefined()
  })
})

describe('useGuestList self-test retry', () => {
  it('asks the backend to run the guest\'s self-test again and reloads so the card shows it testing', async () => {
    const list = start()
    await flushPromises()
    api.guestsList.mockResolvedValue(succeeded([guest('win'), guest('lab1', { state: 'testing', build_id: 'b1' })]))
    await list.retestSelfTest('lab1')
    expect(api.guestsRetrySelftest.mock.calls[0]![0].path).toEqual({ name: 'lab1' })
    expect(list.guests.value.find((g) => g.name === 'lab1')?.state).toBe('testing')
    expect(list.retestErrorOf('lab1')).toBeUndefined()
  })

  it('is busy while the request runs', async () => {
    let answer: (value: unknown) => void = () => undefined
    api.guestsRetrySelftest.mockReturnValue(new Promise((resolve) => (answer = resolve)))
    const list = start()
    await flushPromises()
    const retesting = list.retestSelfTest('lab1')
    expect(list.isRetesting('lab1')).toBe(true)
    expect(list.isRetesting('win')).toBe(false)
    answer(succeeded({ job_id: 3, build_id: 'b1', guest: 'lab1' }))
    await retesting
    expect(list.isRetesting('lab1')).toBe(false)
  })

  it('does not send the request twice while it runs', async () => {
    api.guestsRetrySelftest.mockReturnValue(new Promise(() => undefined))
    const list = start()
    await flushPromises()
    void list.retestSelfTest('lab1')
    void list.retestSelfTest('lab1')
    expect(api.guestsRetrySelftest).toHaveBeenCalledTimes(1)
  })

  it('keeps a refusal on the guest, asks the client not to toast it, and is no longer busy', async () => {
    api.guestsRetrySelftest.mockResolvedValue(failed('lab1 never finished building: restart or resume its build instead', 409))
    const list = start()
    await flushPromises()
    await list.retestSelfTest('lab1')
    expect(list.retestErrorOf('lab1')).toBe('lab1 never finished building: restart or resume its build instead')
    expect(list.isRetesting('lab1')).toBe(false)
    expect(api.guestsRetrySelftest.mock.calls[0]![0].meta).toEqual({ quietStatuses: expect.arrayContaining([409]) })
  })

  it('clears the earlier refusal when it is tried again', async () => {
    api.guestsRetrySelftest.mockResolvedValueOnce(failed('An analysis is running', 409))
    const list = start()
    await flushPromises()
    await list.retestSelfTest('lab1')
    await list.retestSelfTest('lab1')
    expect(list.retestErrorOf('lab1')).toBeUndefined()
  })
})
