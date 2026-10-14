import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify, Quasar, QSelect } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { AnalysisRead, SystemHealth } from '@/api'
import AnalysisRowMenu from '@/components/AnalysisRowMenu.vue'

vi.mock('@/api', () => ({
  analysesList: vi.fn(),
  analysesRead: vi.fn(),
  analysesCreate: vi.fn(),
  analysesCancel: vi.fn(),
  analysesDelete: vi.fn(),
  analysesReingest: vi.fn(),
  systemHealth: vi.fn().mockResolvedValue({ data: undefined }),
  annotationsListTags: vi.fn(),
}))

vi.mock('@/services/ws', () => ({
  createSystemClient: () => ({
    state: { value: 'open' },
    lastMessage: { value: undefined },
    subscribe: () => () => undefined,
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

vi.mock('@/services/confirm', () => ({ confirmDestructive: vi.fn() }))
vi.mock('@/services/submit-dialog', () => ({ openSubmitDialog: vi.fn() }))

const { analysesList, analysesCancel, analysesDelete, analysesReingest, annotationsListTags } = await import('@/api')
const { confirmDestructive } = await import('@/services/confirm')
const { openSubmitDialog } = await import('@/services/submit-dialog')
const { useSystemStore } = await import('@/stores/system')
const DashboardPage = (await import('@/pages/DashboardPage.vue')).default

const GUEST_READY: SystemHealth = {
  postgres: { status: 'ok', message: null },
  opensearch: { status: 'ok', message: null },
  cape: { status: 'ok', message: null },
  guest: { status: 'ok', message: null },
}

const GUEST_MISSING: SystemHealth = {
  ...GUEST_READY,
  guest: { status: 'down', message: 'no guest image found' },
}

function analysis(overrides: Partial<AnalysisRead> = {}): AnalysisRead {
  return {
    id: 1,
    sample_sha256: 'a'.repeat(64),
    filename: 'invoice.exe',
    cape_task_id: null,
    status: 'done',
    phase: 'done',
    options: {},
    score: 8.5,
    max_severity: 'high',
    detected_families: [],
    event_count: 0,
    disk_bytes: 0,
    error: null,
    submitted_at: new Date(2026, 9, 12, 14, 3).toISOString(),
    started_at: null,
    finished_at: null,
    summary: null,
    tags: [],
    ...overrides,
  } as AnalysisRead
}

function listed(items: AnalysisRead[], total = items.length) {
  return { data: { items, total }, error: undefined } as unknown as Awaited<ReturnType<typeof analysesList>>
}

function listFailed(message: string) {
  return { data: undefined, error: { error: { message } } } as unknown as Awaited<ReturnType<typeof analysesList>>
}

async function mountDashboard(options: { health?: SystemHealth | null } = {}) {
  setActivePinia(createPinia())
  useSystemStore().health = options.health === null ? undefined : (options.health ?? GUEST_READY)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: DashboardPage },
      { path: '/analyses/:id/:tab?', name: 'analysis-workspace', component: { template: '<div />' } },
      { path: '/guest', name: 'guest', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  const wrapper = mount(DashboardPage, { global: { plugins: [Quasar, router] } })
  await flushPromises()
  return { wrapper, router }
}

function lastListQuery() {
  const calls = vi.mocked(analysesList).mock.calls
  return calls[calls.length - 1]![0]!.query
}

beforeEach(() => {
  vi.clearAllMocks()
  Notify.create = vi.fn()
  vi.mocked(analysesList).mockResolvedValue(listed([]))
  vi.mocked(annotationsListTags).mockResolvedValue({
    data: [
      { name: 'phishing', count: 7 },
      { name: 'emotet', count: 2 },
    ],
    error: undefined,
  } as Awaited<ReturnType<typeof annotationsListTags>>)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('DashboardPage rows', () => {
  it('lists the fetched analyses', async () => {
    vi.mocked(analysesList).mockResolvedValue(
      listed([analysis({ id: 2, filename: 'loader.dll' }), analysis({ id: 1, filename: 'doc.xlsm' })]),
    )
    const { wrapper } = await mountDashboard()
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('loader.dll')
    expect(rows[1]!.text()).toContain('doc.xlsm')
    expect(wrapper.find('.loader').exists()).toBe(false)
  })

  it('says how many of the matching analyses are shown when the list is paged', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis()], 120))
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('.list-footer').text()).toContain('1 of 120')
  })

  it('opens the analysis workspace when a row is clicked', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 42 })]))
    const { wrapper, router } = await mountDashboard()
    await wrapper.find('tbody tr').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('analysis-workspace')
    expect(router.currentRoute.value.params.id).toBe('42')
  })
})

describe('DashboardPage loading and errors', () => {
  it('shows the loader until the first list arrives', async () => {
    let resolveList: (value: ReturnType<typeof listed>) => void = () => undefined
    vi.mocked(analysesList).mockReturnValue(
      new Promise((resolve) => (resolveList = resolve)) as ReturnType<typeof analysesList>,
    )
    const { wrapper } = await mountDashboard()
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('no analyses yet')

    resolveList(listed([analysis()]))
    await flushPromises()
    expect(wrapper.find('.loader').exists()).toBe(false)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  })

  it('shows the failure message with a retry that fetches again', async () => {
    vi.mocked(analysesList).mockResolvedValueOnce(listFailed('database unreachable'))
    const { wrapper } = await mountDashboard()
    expect(wrapper.text()).toContain('> failed to load: database unreachable')
    expect(wrapper.find('tbody').exists()).toBe(false)

    vi.mocked(analysesList).mockResolvedValueOnce(listed([analysis()]))
    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()
    expect(analysesList).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  })
})

describe('DashboardPage empty states', () => {
  it('invites a first submission when there are no analyses and the guest is ready', async () => {
    const { wrapper } = await mountDashboard()
    expect(wrapper.text()).toContain('> no analyses yet')
    await wrapper.find('.submit-btn').trigger('click')
    expect(openSubmitDialog).toHaveBeenCalledOnce()
  })

  it('explains that the guest is not ready, with its reason, and links to the Guest page', async () => {
    const { wrapper, router } = await mountDashboard({ health: GUEST_MISSING })
    expect(wrapper.text()).toContain('> guest VM not ready')
    expect(wrapper.text()).toContain('no guest image found')
    expect(wrapper.find('.submit-btn').exists()).toBe(false)

    await wrapper.find('.build-guest-btn').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('guest')
  })

  it('does not claim the guest is missing before the health snapshot arrives', async () => {
    const { wrapper } = await mountDashboard({ health: null })
    expect(wrapper.text()).toContain('> no analyses yet')
  })

  it('says nothing matches when filters leave no rows, and clears them on request', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const { wrapper } = await mountDashboard()
    await wrapper.find('.search-input input').setValue('zzz')
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()
    expect(wrapper.text()).toContain('> no analyses match')
    expect(wrapper.find('.submit-btn').exists()).toBe(false)

    await wrapper.find('.clear-filters-btn').trigger('click')
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()
    expect(lastListQuery()).toEqual({})
    expect(wrapper.text()).toContain('> no analyses yet')
  })
})

describe('DashboardPage filters', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  })

  it('fetches unfiltered on mount', async () => {
    await mountDashboard()
    expect(lastListQuery()).toEqual({})
  })

  it('sends the search text once typing pauses, not on every keystroke', async () => {
    const { wrapper } = await mountDashboard()
    const input = wrapper.find('.search-input input')
    await input.setValue('e')
    await input.setValue('evil')
    expect(analysesList).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(400)
    expect(analysesList).toHaveBeenCalledTimes(2)
    expect(lastListQuery()).toEqual({ q: 'evil' })
  })

  it('sends the chosen status, and drops it when cleared', async () => {
    const { wrapper } = await mountDashboard()
    const select = wrapper.findComponent(QSelect)
    select.vm.$emit('update:modelValue', 'failed')
    await vi.advanceTimersByTimeAsync(400)
    expect(lastListQuery()).toEqual({ status: 'failed' })

    select.vm.$emit('update:modelValue', null)
    await vi.advanceTimersByTimeAsync(400)
    expect(lastListQuery()).toEqual({})
  })

  it('combines search and status', async () => {
    const { wrapper } = await mountDashboard()
    await wrapper.find('.search-input input').setValue('evil')
    wrapper.findComponent(QSelect).vm.$emit('update:modelValue', 'done')
    await vi.advanceTimersByTimeAsync(400)
    expect(lastListQuery()).toEqual({ q: 'evil', status: 'done' })
  })
})

describe('DashboardPage tag filter', () => {
  function tagSelect(wrapper: Awaited<ReturnType<typeof mountDashboard>>['wrapper']) {
    return wrapper.findAllComponents(QSelect).find((select) => select.classes().includes('tag-select'))!
  }

  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('offers the tags in use, with how many links use each', async () => {
    const { wrapper } = await mountDashboard()
    expect(tagSelect(wrapper).props('options')).toEqual([
      { value: 'phishing', label: 'phishing (7)' },
      { value: 'emotet', label: 'emotet (2)' },
    ])
  })

  it('sends the chosen tag, and drops it when cleared', async () => {
    const { wrapper } = await mountDashboard()
    tagSelect(wrapper).vm.$emit('update:modelValue', 'emotet')
    await vi.advanceTimersByTimeAsync(400)
    expect(lastListQuery()).toEqual({ tag: 'emotet' })

    tagSelect(wrapper).vm.$emit('update:modelValue', null)
    await vi.advanceTimersByTimeAsync(400)
    expect(lastListQuery()).toEqual({})
  })

  it('combines with the search and the status', async () => {
    const { wrapper } = await mountDashboard()
    await wrapper.find('.search-input input').setValue('evil')
    wrapper.findComponent(QSelect).vm.$emit('update:modelValue', 'done')
    tagSelect(wrapper).vm.$emit('update:modelValue', 'phishing')
    await vi.advanceTimersByTimeAsync(400)
    expect(lastListQuery()).toEqual({ q: 'evil', status: 'done', tag: 'phishing' })
  })

  it('clears with the other filters when nothing matches', async () => {
    const { wrapper } = await mountDashboard()
    tagSelect(wrapper).vm.$emit('update:modelValue', 'emotet')
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()
    expect(wrapper.text()).toContain('no analyses match')

    await wrapper.find('.clear-filters-btn').trigger('click')
    await vi.advanceTimersByTimeAsync(400)
    expect(lastListQuery()).toEqual({})
  })

  it('still lists the analyses when the tags cannot be read', async () => {
    vi.mocked(annotationsListTags).mockResolvedValue({
      data: undefined,
      error: { error: { message: 'down' } },
    } as unknown as Awaited<ReturnType<typeof annotationsListTags>>)
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ filename: 'loader.dll' })]))
    const { wrapper } = await mountDashboard()
    expect(wrapper.text()).toContain('loader.dll')
    expect(tagSelect(wrapper).props('options')).toEqual([])
  })
})

describe('DashboardPage row actions', () => {
  it('deletes after the user confirms and drops the row', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 5, filename: 'old.exe' })]))
    vi.mocked(confirmDestructive).mockResolvedValue(true)
    vi.mocked(analysesDelete).mockResolvedValue({ error: undefined } as Awaited<ReturnType<typeof analysesDelete>>)
    const { wrapper } = await mountDashboard()

    await wrapper.find('[aria-label="Delete analysis 5"]').trigger('click')
    await flushPromises()

    expect(confirmDestructive).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('#5'), message: expect.stringContaining('old.exe') }),
    )
    expect(analysesDelete).toHaveBeenCalledWith({ path: { analysis_id: 5 } })
    expect(wrapper.find('tbody').exists()).toBe(false)
  })

  it('tells the user how much disk the delete frees', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 5, disk_bytes: 2 * 1024 ** 3 })]))
    vi.mocked(confirmDestructive).mockResolvedValue(false)
    const { wrapper } = await mountDashboard()

    await wrapper.find('[aria-label="Delete analysis 5"]').trigger('click')
    await flushPromises()

    expect(confirmDestructive).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('freeing 2 GB') }),
    )
  })

  it('keeps the analysis when the user declines', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 5 })]))
    vi.mocked(confirmDestructive).mockResolvedValue(false)
    const { wrapper } = await mountDashboard()

    await wrapper.find('[aria-label="Delete analysis 5"]').trigger('click')
    await flushPromises()

    expect(analysesDelete).not.toHaveBeenCalled()
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  })

  it('toasts an error and keeps the row when the delete fails', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 5 })]))
    vi.mocked(confirmDestructive).mockResolvedValue(true)
    vi.mocked(analysesDelete).mockResolvedValue({ error: {} } as Awaited<ReturnType<typeof analysesDelete>>)
    const { wrapper } = await mountDashboard()

    await wrapper.find('[aria-label="Delete analysis 5"]').trigger('click')
    await flushPromises()

    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-error' }))
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  })

  it('cancels a queued analysis after confirmation and shows the new status', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 6, status: 'queued', score: null, max_severity: null })]))
    vi.mocked(confirmDestructive).mockResolvedValue(true)
    vi.mocked(analysesCancel).mockResolvedValue({
      data: analysis({ id: 6, status: 'cancelled', score: null, max_severity: null }),
      error: undefined,
    } as unknown as Awaited<ReturnType<typeof analysesCancel>>)
    const { wrapper } = await mountDashboard()

    await wrapper.find('[aria-label="Cancel analysis 6"]').trigger('click')
    await flushPromises()

    expect(analysesCancel).toHaveBeenCalledWith({ path: { analysis_id: 6 } })
    expect(wrapper.find('tbody tr .status-badge').text()).toContain('CANCELLED')
  })

  it('does not cancel when the user declines', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 6, status: 'queued' })]))
    vi.mocked(confirmDestructive).mockResolvedValue(false)
    const { wrapper } = await mountDashboard()

    await wrapper.find('[aria-label="Cancel analysis 6"]').trigger('click')
    await flushPromises()

    expect(analysesCancel).not.toHaveBeenCalled()
  })
})

describe('DashboardPage row menu', () => {
  function rowMenu(wrapper: Awaited<ReturnType<typeof mountDashboard>>['wrapper']) {
    return wrapper.getComponent(AnalysisRowMenu)
  }

  it('opens the analysis from the menu', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 5 })]))
    const { wrapper, router } = await mountDashboard()

    rowMenu(wrapper).vm.$emit('open', 5)
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/analyses/5')
  })

  it('re-ingests and shows the analysis ingesting again', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 5 })]))
    vi.mocked(analysesReingest).mockResolvedValue({
      data: analysis({ id: 5, status: 'ingesting' }),
      error: undefined,
    } as unknown as Awaited<ReturnType<typeof analysesReingest>>)
    const { wrapper } = await mountDashboard()

    rowMenu(wrapper).vm.$emit('reingest', 5)
    await flushPromises()

    expect(analysesReingest).toHaveBeenCalledWith({ path: { analysis_id: 5 } })
    expect(wrapper.find('tbody tr .status-badge').text()).toContain('INGESTING')
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-info', message: 'Re-ingesting #5' }))
  })

  it('adds no toast of its own when the re-ingest is refused, since the API error toast says why', async () => {
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ id: 5 })]))
    vi.mocked(analysesReingest).mockResolvedValue({
      data: undefined,
      error: { error: { message: 'Another analysis is active' } },
    } as unknown as Awaited<ReturnType<typeof analysesReingest>>)
    const { wrapper } = await mountDashboard()

    rowMenu(wrapper).vm.$emit('reingest', 5)
    await flushPromises()

    expect(Notify.create).not.toHaveBeenCalled()
    expect(wrapper.find('tbody tr .status-badge').text()).toContain('DONE')
  })
})

describe('DashboardPage polling', () => {
  it('keeps refreshing while an analysis is running and stops when the page unmounts', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    vi.mocked(analysesList).mockResolvedValue(listed([analysis({ status: 'running', score: null, max_severity: null })]))
    const { wrapper } = await mountDashboard()
    expect(analysesList).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000)
    expect(analysesList).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(analysesList).toHaveBeenCalledTimes(2)
  })
})
