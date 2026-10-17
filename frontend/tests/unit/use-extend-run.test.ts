import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'
import type { AnalysisStatus, ErrorEnvelope } from '@/api'
import { analysisFixture } from './analysis-fixtures'

const analysesExtend = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({ analysesExtend }))

const { useExtendRun } = await import('@/composables/use-extend-run')
const { useAnalysesStore } = await import('@/stores/analyses')
const { quietOn } = await import('@/services/quiet-statuses')
const { EXTEND_STEP_S, LONGEST_RUN_S } = await import('@/services/extend-run')

const STARTED = '2026-10-13T10:00:00Z'
const deadlineAfter = (seconds: number) => new Date(Date.parse(STARTED) + seconds * 1000).toISOString()

let scope: EffectScope
const status = ref<AnalysisStatus>('running')
const interactive = ref(true)
const deadline = ref<string | null>(deadlineAfter(180))
const started = ref<string | null>(STARTED)

function start() {
  scope = effectScope()
  return scope.run(() =>
    useExtendRun({
      analysisId: () => 42,
      status: () => status.value,
      interactive: () => interactive.value,
      deadlineAt: () => deadline.value,
      startedAt: () => started.value,
    }),
  )!
}

const envelope = (message: string): ErrorEnvelope => ({ error: { code: 'conflict', message, details: {} } })
const accepted = (deadlineAt: string) => ({
  data: analysisFixture({ id: 42, status: 'running', options: { interactive: true }, deadline_at: deadlineAt }),
  error: undefined,
  response: { status: 200 },
})
const refused = (httpStatus: number, message: string) => ({ data: undefined, error: envelope(message), response: { status: httpStatus } })

beforeEach(() => {
  setActivePinia(createPinia())
  status.value = 'running'
  interactive.value = true
  deadline.value = deadlineAfter(180)
  started.value = STARTED
  Notify.create = vi.fn()
  analysesExtend.mockResolvedValue(accepted(deadlineAfter(240)))
})

afterEach(() => {
  scope.stop()
  vi.clearAllMocks()
})

describe('useExtendRun visibility', () => {
  it('is visible for an interactive run that is running and has a deadline', () => {
    expect(start().visible.value).toBe(true)
  })

  it('is hidden for a run that is not interactive', () => {
    interactive.value = false
    expect(start().visible.value).toBe(false)
  })

  it.each(['queued', 'starting', 'processing', 'done', 'failed'] as const)('is hidden while the analysis is %s', (hiddenStatus) => {
    status.value = hiddenStatus
    expect(start().visible.value).toBe(false)
  })

  it('is hidden when the run has no deadline yet', () => {
    deadline.value = null
    expect(start().visible.value).toBe(false)
  })
})

describe('useExtendRun at the longest', () => {
  it('is not at the longest while the deadline is short of the limit', () => {
    deadline.value = deadlineAfter(LONGEST_RUN_S - 1)
    expect(start().atLongest.value).toBe(false)
  })

  it('is at the longest once the deadline reaches the limit from the start, and says why', () => {
    deadline.value = deadlineAfter(LONGEST_RUN_S)
    const extend = start()
    expect(extend.atLongest.value).toBe(true)
    expect(extend.disabled.value).toBe(true)
    expect(extend.title.value).toBe('The run is already at its longest (20 minutes)')
  })

  it('is not at the longest without a start time', () => {
    started.value = null
    expect(start().atLongest.value).toBe(false)
  })
})

describe('useExtendRun pressing', () => {
  it('extends the run by the step, asking the interceptor to leave 409 to it', async () => {
    await start().press()
    expect(analysesExtend).toHaveBeenCalledWith({ path: { analysis_id: 42 }, body: { seconds: EXTEND_STEP_S }, meta: quietOn(409) })
    expect(EXTEND_STEP_S).toBe(60)
  })

  it('does nothing when the run is at its longest', async () => {
    deadline.value = deadlineAfter(LONGEST_RUN_S)
    await start().press()
    expect(analysesExtend).not.toHaveBeenCalled()
  })

  it('does nothing when the button is not visible', async () => {
    interactive.value = false
    await start().press()
    expect(analysesExtend).not.toHaveBeenCalled()
  })

  it('is pending while the request is in flight and does not send a second one', async () => {
    let respond!: (value: unknown) => void
    analysesExtend.mockReturnValue(new Promise((resolve) => (respond = resolve)))
    const extend = start()
    const first = extend.press()
    expect(extend.pending.value).toBe(true)
    expect(extend.disabled.value).toBe(true)
    await extend.press()
    expect(analysesExtend).toHaveBeenCalledTimes(1)
    respond(accepted(deadlineAfter(240)))
    await first
    expect(extend.pending.value).toBe(false)
  })
})

describe('useExtendRun on success', () => {
  it('puts the returned analysis into the analyses store, so the header and the cap follow at once', async () => {
    const store = useAnalysesStore()
    store.current = analysisFixture({ id: 42, status: 'running', options: { interactive: true }, deadline_at: deadlineAfter(180) })
    await start().press()
    expect(store.current?.deadline_at).toBe(deadlineAfter(240))
  })

  it('keeps the store in step with the list when the analysis is listed too', async () => {
    const store = useAnalysesStore()
    store.items = [analysisFixture({ id: 42, status: 'running', options: { interactive: true }, deadline_at: deadlineAfter(180) })]
    await start().press()
    expect(store.items[0]?.deadline_at).toBe(deadlineAfter(240))
  })
})

describe('useExtendRun when the server refuses', () => {
  it('toasts the reason of a 409 and leaves the store and the button as they were', async () => {
    const message = 'The run is already at its longest (20 minutes)'
    analysesExtend.mockResolvedValue(refused(409, message))
    const store = useAnalysesStore()
    store.current = analysisFixture({ id: 42, status: 'running', options: { interactive: true }, deadline_at: deadlineAfter(180) })
    const extend = start()
    await extend.press()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-warning', message }))
    expect(store.current?.deadline_at).toBe(deadlineAfter(180))
    expect(extend.pending.value).toBe(false)
  })

  it('leaves a 502 toast to the interceptor and gives the button back', async () => {
    analysesExtend.mockResolvedValue(refused(502, 'guest agent unreachable'))
    const extend = start()
    await extend.press()
    await flushPromises()
    expect(Notify.create).not.toHaveBeenCalled()
    expect(extend.pending.value).toBe(false)
  })

  it('gives the button back after a failure with no HTTP response', async () => {
    analysesExtend.mockResolvedValue({ data: undefined, error: new TypeError('Failed to fetch'), response: undefined })
    const extend = start()
    await extend.press()
    expect(Notify.create).not.toHaveBeenCalled()
    expect(extend.pending.value).toBe(false)
  })
})
