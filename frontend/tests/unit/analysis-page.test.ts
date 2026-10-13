import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import type { AnalysisRead, ErrorEnvelope } from '@/api'
import {
  analysisWithStatus,
  DETECTIONS_SUMMARY,
  NO_DETECTIONS_SUMMARY,
} from './analysis-fixtures'

const analysesReadMock = vi.fn()
const analysesCancelMock = vi.fn()
const analysesDeleteMock = vi.fn()
vi.mock('@/api', () => ({
  analysesRead: (...args: unknown[]) => analysesReadMock(...args),
  analysesCancel: (...args: unknown[]) => analysesCancelMock(...args),
  analysesDelete: (...args: unknown[]) => analysesDeleteMock(...args),
  analysesList: vi.fn(),
  analysesCreate: vi.fn(),
}))

const confirmDestructiveMock = vi.fn()
vi.mock('@/services/confirm', () => ({
  confirmDestructive: (...args: unknown[]) => confirmDestructiveMock(...args),
}))

const route = reactive<{ params: { id: string; tab?: string } }>({ params: { id: '42' } })
const push = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ push }),
}))

const { default: AnalysisPage } = await import('@/pages/AnalysisPage.vue')

const POLL_MS = 2_000

const succeeded = <T>(data: T) => ({ data, error: undefined })

function failed(message = 'Analysis 42 not found') {
  const error: ErrorEnvelope = { error: { code: 'not_found', message, details: {} } }
  return { data: undefined, error }
}

async function mountPage(analysis: AnalysisRead = analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })) {
  analysesReadMock.mockResolvedValue(succeeded(analysis))
  const wrapper = mount(AnalysisPage, { global: { plugins: [Quasar] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  setActivePinia(createPinia())
  route.params = { id: '42' }
  Notify.create = vi.fn()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AnalysisPage loading', () => {
  it('shows a loader until the analysis arrives, then the header', async () => {
    let resolveRead: (value: unknown) => void = () => undefined
    analysesReadMock.mockReturnValue(new Promise((resolve) => (resolveRead = resolve)))
    const wrapper = mount(AnalysisPage, { global: { plugins: [Quasar] } })
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.find('.analysis-header').exists()).toBe(false)

    resolveRead(succeeded(analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })))
    await flushPromises()
    expect(wrapper.find('.loader').exists()).toBe(false)
    expect(wrapper.find('.analysis-header').exists()).toBe(true)
  })

  it('reads the analysis named by the route', async () => {
    await mountPage()
    expect(analysesReadMock).toHaveBeenCalledWith({ path: { analysis_id: 42 } })
  })

  it('shows the failure message with a retry that loads again', async () => {
    analysesReadMock.mockResolvedValue(failed())
    const wrapper = mount(AnalysisPage, { global: { plugins: [Quasar] } })
    await flushPromises()
    expect(wrapper.text()).toContain('failed to load: Analysis 42 not found')

    analysesReadMock.mockResolvedValue(succeeded(analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })))
    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.analysis-header').exists()).toBe(true)
  })

  it('reports a non-numeric id as not found without asking the backend', async () => {
    route.params = { id: 'abc' }
    const wrapper = mount(AnalysisPage, { global: { plugins: [Quasar] } })
    await flushPromises()
    expect(analysesReadMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('not found')
  })

  it('loads the new analysis when the route id changes', async () => {
    const wrapper = await mountPage()
    analysesReadMock.mockResolvedValue(succeeded(analysisWithStatus('done', { id: 43, summary: NO_DETECTIONS_SUMMARY })))
    route.params = { id: '43' }
    await flushPromises()
    expect(analysesReadMock).toHaveBeenLastCalledWith({ path: { analysis_id: 43 } })
    expect(wrapper.find('.analysis-header').text()).toContain('#43')
  })
})

describe('AnalysisPage states', () => {
  it('shows a queued analysis as waiting', async () => {
    const wrapper = await mountPage(analysisWithStatus('queued', { started_at: null, finished_at: null }))
    expect(wrapper.find('.analysis-header').text()).toContain('QUEUED')
    expect(wrapper.text()).toContain('waiting')
  })

  it.each(['starting', 'running', 'processing', 'ingesting'] as const)('shows progress while %s', async (status) => {
    const wrapper = await mountPage(analysisWithStatus(status, { finished_at: null }))
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(true)
  })

  it('shows the detections of a finished analysis', async () => {
    const wrapper = await mountPage(
      analysisWithStatus('done', { score: 6, max_severity: 'high', summary: DETECTIONS_SUMMARY }),
    )
    expect(wrapper.findAll('.signature-row')).toHaveLength(3)
  })

  it('says there were no detections for a clean finished analysis', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('no detections')
  })

  it.each(['failed', 'report_failed'] as const)('shows the error banner of a %s analysis', async (status) => {
    const wrapper = await mountPage(analysisWithStatus(status, { error: 'CAPE went away' }))
    expect(wrapper.find('[role="alert"]').text()).toContain('CAPE went away')
  })

  it('shows a cancelled analysis', async () => {
    const wrapper = await mountPage(analysisWithStatus('cancelled', { started_at: null, finished_at: null }))
    expect(wrapper.find('.analysis-header').text()).toContain('CANCELLED')
  })
})

describe('AnalysisPage tabs', () => {
  it('shows the summary by default', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('.analysis-summary').exists()).toBe(true)
  })

  it('shows a placeholder for a tab that arrives with M1b', async () => {
    route.params = { id: '42', tab: 'processes' }
    const wrapper = await mountPage()
    expect(wrapper.find('.analysis-summary').exists()).toBe(false)
    expect(wrapper.text()).toContain('processes arrives with M1b')
  })

  it('navigates when the summary tab is selected', async () => {
    route.params = { id: '42', tab: 'processes' }
    const wrapper = await mountPage()
    await wrapper.find('.analysis-tabs button:not([disabled])').trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'analysis-workspace', params: { id: '42', tab: 'summary' } })
  })
})

describe('AnalysisPage polling', () => {
  it('keeps a running analysis fresh until it finishes, then stops', async () => {
    const wrapper = await mountPage(analysisWithStatus('running', { finished_at: null }))
    expect(analysesReadMock).toHaveBeenCalledTimes(1)

    analysesReadMock.mockResolvedValue(succeeded(analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })))
    await vi.advanceTimersByTimeAsync(POLL_MS)
    expect(analysesReadMock).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.analysis-header').text()).toContain('DONE')

    await vi.advanceTimersByTimeAsync(POLL_MS * 3)
    expect(analysesReadMock).toHaveBeenCalledTimes(2)
  })

  it('stops polling when the page is left', async () => {
    const wrapper = await mountPage(analysisWithStatus('running', { finished_at: null }))
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(POLL_MS * 3)
    expect(analysesReadMock).toHaveBeenCalledTimes(1)
  })

  it('does not poll a finished analysis', async () => {
    await mountPage()
    await vi.advanceTimersByTimeAsync(POLL_MS * 3)
    expect(analysesReadMock).toHaveBeenCalledTimes(1)
  })
})

describe('AnalysisPage cancel', () => {
  const queued = () => analysisWithStatus('queued', { started_at: null, finished_at: null })

  it('cancels the queued analysis and shows it cancelled', async () => {
    const wrapper = await mountPage(queued())
    analysesCancelMock.mockResolvedValue(succeeded(analysisWithStatus('cancelled', { started_at: null })))
    await wrapper.find('.analysis-header__cancel').trigger('click')
    await flushPromises()
    expect(analysesCancelMock).toHaveBeenCalledWith({ path: { analysis_id: 42 } })
    expect(wrapper.find('.analysis-header').text()).toContain('CANCELLED')
    expect(wrapper.find('.analysis-header__cancel').exists()).toBe(false)
  })

  it('tells the user when the cancel is refused', async () => {
    const wrapper = await mountPage(queued())
    analysesCancelMock.mockResolvedValue(failed('Analysis 42 is no longer queued'))
    await wrapper.find('.analysis-header__cancel').trigger('click')
    await flushPromises()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
    expect(wrapper.find('.analysis-header').text()).toContain('QUEUED')
  })
})

describe('AnalysisPage delete', () => {
  it('deletes after confirmation and returns to the dashboard', async () => {
    const wrapper = await mountPage()
    confirmDestructiveMock.mockResolvedValue(true)
    analysesDeleteMock.mockResolvedValue({ data: undefined, error: undefined })
    await wrapper.find('.analysis-header__delete').trigger('click')
    await flushPromises()
    expect(confirmDestructiveMock).toHaveBeenCalledWith(expect.objectContaining({ title: expect.any(String) }))
    expect(analysesDeleteMock).toHaveBeenCalledWith({ path: { analysis_id: 42 } })
    expect(push).toHaveBeenCalledWith({ name: 'dashboard' })
  })

  it('does nothing when the confirmation is declined', async () => {
    const wrapper = await mountPage()
    confirmDestructiveMock.mockResolvedValue(false)
    await wrapper.find('.analysis-header__delete').trigger('click')
    await flushPromises()
    expect(analysesDeleteMock).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
  })

  it('stays on the page and tells the user when the delete is refused', async () => {
    const wrapper = await mountPage()
    confirmDestructiveMock.mockResolvedValue(true)
    analysesDeleteMock.mockResolvedValue(failed('Analysis 42 is still running'))
    await wrapper.find('.analysis-header__delete').trigger('click')
    await flushPromises()
    expect(push).not.toHaveBeenCalled()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
    expect(wrapper.find('.analysis-header').exists()).toBe(true)
  })
})
