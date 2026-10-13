import { flushPromises } from '@vue/test-utils'
import { Notify } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'
import type { AnalysisStatus, ErrorEnvelope } from '@/api'
import { analysisFixture } from './analysis-fixtures'

const analysesFinish = vi.hoisted(() => vi.fn())
const confirmDestructive = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({ analysesFinish }))
vi.mock('@/services/confirm', () => ({ confirmDestructive }))

const { useEndRun, COOLDOWN_MS, GIVE_UP_MS } = await import('@/composables/use-end-run')
const { quietOn } = await import('@/services/quiet-statuses')

let scope: EffectScope
const status = ref<AnalysisStatus>('running')
const monitorUp = ref(true)

function start() {
  scope = effectScope()
  return scope.run(() => useEndRun({ analysisId: () => 45, status: () => status.value, monitorUp: () => monitorUp.value }))!
}

const envelope = (message: string): ErrorEnvelope => ({ error: { code: 'conflict', message, details: {} } })
const accepted = () => ({ data: analysisFixture({ id: 45, status: 'running' }), error: undefined, response: { status: 200 } })
const refused = (httpStatus: number, message: string) => ({ data: undefined, error: envelope(message), response: { status: httpStatus } })

beforeEach(() => {
  vi.useFakeTimers()
  status.value = 'running'
  monitorUp.value = true
  Notify.create = vi.fn()
  confirmDestructive.mockResolvedValue(true)
  analysesFinish.mockResolvedValue(accepted())
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
  vi.clearAllMocks()
})

describe('useEndRun phases', () => {
  it('is ready for a running analysis whose monitor is up', () => {
    expect(start().phase.value).toBe('ready')
  })

  it('waits, with a reason, until the monitor is up', async () => {
    monitorUp.value = false
    const endRun = start()
    expect(endRun.phase.value).toBe('waiting')
    expect(endRun.title.value).toMatch(/not started in the guest yet/)
    monitorUp.value = true
    await flushPromises()
    expect(endRun.phase.value).toBe('ready')
  })

  it.each(['queued', 'starting', 'processing', 'done', 'failed'] as const)('is hidden while the analysis is %s', (hiddenStatus) => {
    status.value = hiddenStatus
    expect(start().phase.value).toBe('hidden')
  })

  it('does nothing when pressed while waiting', async () => {
    monitorUp.value = false
    await start().press()
    expect(confirmDestructive).not.toHaveBeenCalled()
    expect(analysesFinish).not.toHaveBeenCalled()
  })
})

describe('useEndRun pressing', () => {
  it('asks for confirmation with the wording of the design before calling the server', async () => {
    const endRun = start()
    let answer!: (confirmed: boolean) => void
    confirmDestructive.mockReturnValue(new Promise<boolean>((resolve) => (answer = resolve)))
    const pressed = endRun.press()
    expect(endRun.phase.value).toBe('confirming')
    expect(confirmDestructive).toHaveBeenCalledWith({
      title: 'End the run now?',
      message: 'The guest stops at once and CAPE processes what was collected so far. This cannot be resumed.',
      confirmLabel: 'END RUN',
    })
    expect(analysesFinish).not.toHaveBeenCalled()
    answer(false)
    await pressed
    expect(endRun.phase.value).toBe('ready')
  })

  it('does not call the server when the dialog is cancelled', async () => {
    confirmDestructive.mockResolvedValue(false)
    await start().press()
    expect(analysesFinish).not.toHaveBeenCalled()
  })

  it('ends the run of its analysis, asking the interceptor to leave 409 to it, and shows ENDING', async () => {
    const endRun = start()
    await endRun.press()
    expect(analysesFinish).toHaveBeenCalledWith({ path: { analysis_id: 45 }, meta: quietOn(409) })
    expect(endRun.phase.value).toBe('ending')
    expect(endRun.requested.value).toBe(true)
    expect(Notify.create).not.toHaveBeenCalled()
  })

  it('does not ask twice while a request is in flight', async () => {
    let respond!: (value: unknown) => void
    analysesFinish.mockReturnValue(new Promise((resolve) => (respond = resolve)))
    const endRun = start()
    const first = endRun.press()
    await flushPromises()
    expect(endRun.phase.value).toBe('ending')
    await endRun.press()
    expect(confirmDestructive).toHaveBeenCalledTimes(1)
    respond(accepted())
    await first
    expect(analysesFinish).toHaveBeenCalledTimes(1)
  })

  it('does not open a second dialog while one is open', async () => {
    confirmDestructive.mockReturnValue(new Promise(() => undefined))
    const endRun = start()
    void endRun.press()
    await endRun.press()
    expect(confirmDestructive).toHaveBeenCalledTimes(1)
  })
})

describe('useEndRun after the server accepted', () => {
  it('is hidden once the status leaves running, and is not requested any more', async () => {
    const endRun = start()
    await endRun.press()
    status.value = 'processing'
    await flushPromises()
    expect(endRun.phase.value).toBe('hidden')
    expect(endRun.requested.value).toBe(false)
  })

  it('gives the button back with a toast when the run is still going after 45 s', async () => {
    const endRun = start()
    await endRun.press()
    await vi.advanceTimersByTimeAsync(GIVE_UP_MS - 1)
    expect(endRun.phase.value).toBe('ending')
    await vi.advanceTimersByTimeAsync(1)
    expect(endRun.phase.value).toBe('ready')
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-warning', message: 'The run is taking long to end' }))
  })

  it('stays quiet when the run ended before the 45 s were up', async () => {
    const endRun = start()
    await endRun.press()
    await vi.advanceTimersByTimeAsync(GIVE_UP_MS / 2)
    status.value = 'processing'
    await vi.advanceTimersByTimeAsync(GIVE_UP_MS)
    expect(Notify.create).not.toHaveBeenCalled()
  })

  it('does not arm the 45 s timer for a run that ended while the request was in flight', async () => {
    analysesFinish.mockImplementation(() => {
      status.value = 'processing'
      return Promise.resolve(accepted())
    })
    const endRun = start()
    await endRun.press()
    await vi.advanceTimersByTimeAsync(GIVE_UP_MS)
    expect(Notify.create).not.toHaveBeenCalled()
    expect(endRun.requested.value).toBe(false)
  })

  it('cancels its timer when the scope ends', async () => {
    const endRun = start()
    await endRun.press()
    scope.stop()
    await vi.advanceTimersByTimeAsync(GIVE_UP_MS)
    expect(Notify.create).not.toHaveBeenCalled()
    expect(endRun.phase.value).toBe('ending')
  })
})

describe('useEndRun label', () => {
  it('reads END RUN, then ENDING... once the run is being ended', async () => {
    const endRun = start()
    expect(endRun.label.value).toBe('END RUN')
    await endRun.press()
    expect(endRun.label.value).toBe('ENDING...')
  })
})

describe('useEndRun when the server refuses', () => {
  it('tells calmly, with the server message, that the guest has not started, and waits a few seconds', async () => {
    const message = 'Analysis 45 has not started in the guest yet: wait a few seconds'
    analysesFinish.mockResolvedValue(refused(409, message))
    const endRun = start()
    await endRun.press()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-warning', message }))
    expect(endRun.phase.value).toBe('waiting')
    expect(endRun.requested.value).toBe(false)
    await vi.advanceTimersByTimeAsync(COOLDOWN_MS)
    expect(endRun.phase.value).toBe('ready')
  })

  it('is not an error for the user when a 409 says the run is over: no toast, and the status decides', async () => {
    analysesFinish.mockImplementation(() => {
      status.value = 'processing'
      return Promise.resolve(refused(409, 'Analysis 45 is processing: its run is already over'))
    })
    const endRun = start()
    await endRun.press()
    expect(Notify.create).not.toHaveBeenCalled()
    expect(endRun.phase.value).toBe('hidden')
  })

  it('leaves the 502 toast to the interceptor and gives the button back at once', async () => {
    analysesFinish.mockResolvedValue(refused(502, 'The run could not be ended: guest agent unreachable'))
    const endRun = start()
    await endRun.press()
    expect(Notify.create).not.toHaveBeenCalled()
    expect(endRun.phase.value).toBe('ready')
    expect(endRun.requested.value).toBe(false)
  })

  it('gives the button back after a failure with no HTTP response', async () => {
    analysesFinish.mockResolvedValue({ data: undefined, error: new TypeError('Failed to fetch'), response: undefined })
    const endRun = start()
    await endRun.press()
    expect(endRun.phase.value).toBe('ready')
  })

  it('can try again after a 502', async () => {
    analysesFinish.mockResolvedValueOnce(refused(502, 'nope'))
    const endRun = start()
    await endRun.press()
    await endRun.press()
    expect(analysesFinish).toHaveBeenCalledTimes(2)
    expect(endRun.phase.value).toBe('ending')
  })
})
