import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive, type PropType } from 'vue'
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
  viewsArtifacts: () => Promise.resolve({ data: { screenshots: [] }, error: undefined }),
}))

// The tabs are tested on their own; here only that the page renders the one that was asked for.
vi.mock('@/components/tabs', async () => {
  const { defineComponent, h } = await import('vue')
  const stub = (tab: string) => ({ render: () => h('section', { 'data-tab': tab }) })
  const live = defineComponent({
    props: { analysis: { type: Object as PropType<AnalysisRead>, required: true } },
    emits: ['open-tab'],
    setup: (props, { emit }) => () =>
      h('section', { 'data-tab': 'live', 'data-analysis': props.analysis.id }, [
        h('button', { class: 'live-stub__summary', onClick: () => emit('open-tab', 'summary') }),
      ]),
  })
  return {
    TAB_VIEWS: {
      live,
      ...Object.fromEntries(['processes', 'events', 'network', 'artifacts', 'detections'].map((tab) => [tab, stub(tab)])),
    },
  }
})

// The bar is tested on its own; here only where the page puts it and what it is bound to.
vi.mock('@/components/QueryHeader.vue', async () => {
  const { h } = await import('vue')
  return {
    default: {
      props: { analysisId: { type: Number, required: true } },
      setup: (props: { analysisId: number }) => () =>
        h('div', { class: 'query-header-stub', 'data-analysis': props.analysisId }),
    },
  }
})

const confirmDestructiveMock = vi.fn()
vi.mock('@/services/confirm', () => ({
  confirmDestructive: (...args: unknown[]) => confirmDestructiveMock(...args),
}))

const route = reactive<{ params: { id: string; tab?: string }; query: Record<string, string | string[]> }>({
  params: { id: '42' },
  query: {},
})
const push = vi.fn()
const replace = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ push, replace }),
}))

const { deleteConfirmation } = await import('@/services/delete-confirmation')
const { default: AnalysisPage } = await import('@/pages/AnalysisPage.vue')
const { useQueryStateStore } = await import('@/stores/query-state')

const POLL_MS = 2_000

const succeeded = <T>(data: T) => ({ data, error: undefined })

function failed(message = 'Analysis 42 not found', status = 404) {
  const error: ErrorEnvelope = { error: { code: status === 404 ? 'not_found' : 'internal_error', message, details: {} } }
  return { data: undefined, error, response: { status } }
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
  route.query = {}
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
    expect(analysesReadMock).toHaveBeenCalledWith(expect.objectContaining({ path: { analysis_id: 42 } }))
  })

  it('shows the failure message with a retry that loads again', async () => {
    analysesReadMock.mockResolvedValue(failed('database connection lost', 500))
    const wrapper = mount(AnalysisPage, { global: { plugins: [Quasar] } })
    await flushPromises()
    expect(wrapper.text()).toContain('failed to load: database connection lost')

    analysesReadMock.mockResolvedValue(succeeded(analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })))
    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.analysis-header').exists()).toBe(true)
  })

  it('reports an id the backend does not know as not found, with no retry', async () => {
    analysesReadMock.mockResolvedValue(failed())
    const wrapper = mount(AnalysisPage, { global: { plugins: [Quasar] } })
    await flushPromises()
    expect(wrapper.text()).toContain('analysis not found')
    expect(wrapper.text()).not.toContain('failed to load')
    expect(wrapper.find('.retry-btn').exists()).toBe(false)
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
    expect(analysesReadMock).toHaveBeenLastCalledWith(expect.objectContaining({ path: { analysis_id: 43 } }))
    expect(wrapper.find('.analysis-header').text()).toContain('#43')
  })
})

describe('AnalysisPage states', () => {
  it('shows a queued analysis as waiting', async () => {
    route.params = { id: '42', tab: 'summary' }
    const wrapper = await mountPage(analysisWithStatus('queued', { started_at: null, finished_at: null }))
    expect(wrapper.find('.analysis-header').text()).toContain('QUEUED')
    expect(wrapper.text()).toContain('waiting')
  })

  it.each(['starting', 'running', 'processing', 'ingesting'] as const)('shows progress while %s', async (status) => {
    route.params = { id: '42', tab: 'summary' }
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

  it('shows a placeholder, saying when, for a tab that is not built yet', async () => {
    route.params = { id: '42', tab: 'timeline' }
    const wrapper = await mountPage()
    expect(wrapper.find('.analysis-summary').exists()).toBe(false)
    expect(wrapper.text()).toContain('timeline arrives with M3')
  })

  it.each(['processes', 'events', 'network', 'artifacts', 'detections'])('shows the %s view of a finished analysis', async (tab) => {
    route.params = { id: '42', tab }
    const wrapper = await mountPage()
    await vi.waitFor(() => expect(wrapper.find(`[data-tab="${tab}"]`).exists()).toBe(true))
    expect(wrapper.find('.analysis-summary').exists()).toBe(false)
  })

  it('holds the exploring views back until the analysis is done', async () => {
    route.params = { id: '42', tab: 'processes' }
    const wrapper = await mountPage(analysisWithStatus('running', { finished_at: null }))
    await flushPromises()
    expect(wrapper.find('[data-tab="processes"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('available once the analysis is done')
  })

  it('leaves SUMMARY marked, and marks nothing else, for a tab that is not built yet', async () => {
    route.params = { id: '42', tab: 'timeline' }
    const wrapper = await mountPage()
    const selected = wrapper.findAll('.analysis-tabs [aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['SUMMARY'])
  })

  it('navigates when a tab is selected', async () => {
    route.params = { id: '42', tab: 'processes' }
    const wrapper = await mountPage()
    await wrapper.find('.analysis-tabs button:not([disabled])').trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'analysis-workspace', params: { id: '42', tab: 'summary' }, query: {} })
  })

  it('keeps the query, the chips and the selected process in the URL when a tab is selected', async () => {
    route.params = { id: '42', tab: 'events' }
    route.query = { q: 'lane:file', pid: '4120' }
    const wrapper = await mountPage()
    await wrapper.find('.analysis-tabs button:not([disabled])').trigger('click')
    expect(push).toHaveBeenCalledWith({
      name: 'analysis-workspace',
      params: { id: '42', tab: 'summary' },
      query: { q: 'lane:file', pid: '4120' },
    })
  })
})

describe('AnalysisPage query bar', () => {
  it('shows the query bar under the tabs of the events tab, for this analysis', async () => {
    route.params = { id: '42', tab: 'events' }
    const wrapper = await mountPage()
    const header = wrapper.find('.query-header-stub')
    expect(header.attributes('data-analysis')).toBe('42')
    expect(wrapper.find('.analysis-tabs').element.nextElementSibling).toBe(header.element)
  })

  it.each(['summary', 'processes', 'network', 'artifacts', 'detections'])('has no query bar on the %s tab', async (tab) => {
    route.params = { id: '42', tab }
    const wrapper = await mountPage()
    expect(wrapper.find('.query-header-stub').exists()).toBe(false)
  })

  it('has no query bar on the timeline while that tab is not built', async () => {
    route.params = { id: '42', tab: 'timeline' }
    const wrapper = await mountPage()
    expect(wrapper.find('.query-header-stub').exists()).toBe(false)
  })

  it('has no query bar before the analysis is done: there is nothing to query yet', async () => {
    route.params = { id: '42', tab: 'events' }
    const wrapper = await mountPage(analysisWithStatus('running', { finished_at: null }))
    expect(wrapper.find('.query-header-stub').exists()).toBe(false)
  })

  it('fills the shared query state from the URL and binds it to the analysis', async () => {
    route.params = { id: '42', tab: 'events' }
    route.query = { q: 'lane:file', f: '-api:NtDelayExecution', pid: '4120' }
    await mountPage()
    const store = useQueryStateStore()
    expect(store.analysisId).toBe(42)
    expect(store.urlState).toEqual({
      text: 'lane:file',
      chips: [{ field: 'api', value: 'NtDelayExecution', negate: true }],
      pids: [4120],
      timeRange: null,
    })
  })

  it('starts the state over for another analysis', async () => {
    route.params = { id: '42', tab: 'events' }
    route.query = { q: 'lane:file' }
    await mountPage()
    analysesReadMock.mockResolvedValue(succeeded(analysisWithStatus('done', { id: 43, summary: NO_DETECTIONS_SUMMARY })))
    route.params = { id: '43', tab: 'events' }
    route.query = {}
    await flushPromises()
    expect(useQueryStateStore().isEmpty).toBe(true)
  })
})

describe('AnalysisPage live tab', () => {
  const active = () => analysisWithStatus('running', { finished_at: null })
  const tabLabels = (wrapper: Awaited<ReturnType<typeof mountPage>>) =>
    wrapper.findAll('.analysis-tabs button').map((tab) => tab.text())
  const selectedTabs = (wrapper: Awaited<ReturnType<typeof mountPage>>) =>
    wrapper.findAll('.analysis-tabs [aria-selected="true"]').map((tab) => tab.text())

  it.each(['queued', 'starting', 'running', 'processing', 'ingesting'] as const)(
    'opens an analysis that is %s on LIVE when no tab is in the URL',
    async (status) => {
      const wrapper = await mountPage(analysisWithStatus(status, { finished_at: null }))
      await vi.waitFor(() => expect(wrapper.find('[data-tab="live"]').exists()).toBe(true))
      expect(tabLabels(wrapper)[0]).toBe('LIVE')
      expect(selectedTabs(wrapper)).toEqual(['LIVE'])
      expect(wrapper.find('.analysis-summary').exists()).toBe(false)
    },
  )

  it('shows LIVE for an active analysis opened on the live tab', async () => {
    route.params = { id: '42', tab: 'live' }
    const wrapper = await mountPage(active())
    expect(wrapper.find('[data-tab="live"]').exists()).toBe(true)
  })

  it('gives the live tab the analysis it is about', async () => {
    const wrapper = await mountPage(active())
    expect(wrapper.find('[data-tab="live"]').attributes('data-analysis')).toBe('42')
  })

  it('opens an active analysis on the tab the URL names, and still lists LIVE', async () => {
    route.params = { id: '42', tab: 'summary' }
    const wrapper = await mountPage(active())
    expect(wrapper.find('.analysis-summary').exists()).toBe(true)
    expect(tabLabels(wrapper)[0]).toBe('LIVE')
    expect(selectedTabs(wrapper)).toEqual(['SUMMARY'])
  })

  it('lets the user leave LIVE for another tab and come back to it while the analysis runs', async () => {
    const wrapper = await mountPage(active())
    route.params = { id: '42', tab: 'processes' }
    await flushPromises()
    expect(tabLabels(wrapper)[0]).toBe('LIVE')
    expect(wrapper.find('[data-tab="live"]').exists()).toBe(false)

    route.params = { id: '42', tab: 'live' }
    await flushPromises()
    expect(wrapper.find('[data-tab="live"]').exists()).toBe(true)
    expect(selectedTabs(wrapper)).toEqual(['LIVE'])
  })

  it('opens a finished analysis on SUMMARY with no LIVE tab', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('.analysis-summary').exists()).toBe(true)
    expect(tabLabels(wrapper)).not.toContain('LIVE')
  })

  it('never offers LIVE for an analysis opened already finished, even by its URL', async () => {
    route.params = { id: '42', tab: 'live' }
    const wrapper = await mountPage()
    expect(wrapper.find('[data-tab="live"]').exists()).toBe(false)
    expect(wrapper.find('.analysis-summary').exists()).toBe(true)
    expect(tabLabels(wrapper)).not.toContain('LIVE')
  })

  it('keeps the user on LIVE, and keeps the tab, when the analysis finishes meanwhile', async () => {
    const wrapper = await mountPage(active())
    const liveView = wrapper.find('[data-tab="live"]').element

    analysesReadMock.mockResolvedValue(succeeded(analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })))
    await vi.advanceTimersByTimeAsync(POLL_MS)

    expect(wrapper.find('.analysis-header').text()).toContain('DONE')
    expect(wrapper.find('[data-tab="live"]').element).toBe(liveView)
    expect(selectedTabs(wrapper)).toEqual(['LIVE'])
    expect(wrapper.find('.analysis-summary').exists()).toBe(false)
  })

  it('keeps the LIVE tab listed after the analysis finished, so the user can come back to it', async () => {
    const wrapper = await mountPage(active())
    analysesReadMock.mockResolvedValue(succeeded(analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })))
    await vi.advanceTimersByTimeAsync(POLL_MS)

    route.params = { id: '42', tab: 'summary' }
    await flushPromises()
    expect(tabLabels(wrapper)[0]).toBe('LIVE')
    expect(wrapper.find('.analysis-summary').exists()).toBe(true)

    route.params = { id: '42', tab: 'live' }
    await flushPromises()
    expect(wrapper.find('[data-tab="live"]').exists()).toBe(true)
    expect(selectedTabs(wrapper)).toEqual(['LIVE'])
  })

  it('goes to the tab the live view asks for', async () => {
    const wrapper = await mountPage(active())
    await wrapper.find('.live-stub__summary').trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'analysis-workspace', params: { id: '42', tab: 'summary' }, query: {} })
  })

  it('selects LIVE through the tab bar', async () => {
    route.params = { id: '42', tab: 'summary' }
    const wrapper = await mountPage(active())
    route.params = { id: '42', tab: 'live' }
    await flushPromises()
    expect(tabLabels(wrapper)[0]).toBe('LIVE')
    expect(selectedTabs(wrapper)).toEqual(['LIVE'])
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
    expect(confirmDestructiveMock).toHaveBeenCalledWith(deleteConfirmation(analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY })))
    expect(analysesDeleteMock).toHaveBeenCalledWith({ path: { analysis_id: 42 } })
    expect(push).toHaveBeenCalledWith({ name: 'dashboard' })
  })

  it('tells the user how much disk the delete frees', async () => {
    const wrapper = await mountPage(
      analysisWithStatus('done', { summary: NO_DETECTIONS_SUMMARY, disk_bytes: 3 * 1024 * 1024 }),
    )
    confirmDestructiveMock.mockResolvedValue(false)
    await wrapper.find('.analysis-header__delete').trigger('click')
    await flushPromises()
    expect(confirmDestructiveMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('freeing 3 MB') }),
    )
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
