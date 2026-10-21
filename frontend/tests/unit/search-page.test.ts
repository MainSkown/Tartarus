import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { t } from '@/i18n'
import { eventFixture } from './events-fixtures'

const searchAcrossAnalysesMock = vi.fn()
vi.mock('@/api', () => ({
  searchAcrossAnalyses: (...args: unknown[]) => searchAcrossAnalysesMock(...args),
  queryFields: vi.fn().mockResolvedValue({ data: [], error: undefined }),
  queryValues: vi.fn().mockResolvedValue({ data: { values: [] }, error: undefined }),
  queryValidate: vi.fn().mockResolvedValue({ data: { ok: true, errors: [] }, error: undefined }),
}))

const { default: SearchPage } = await import('@/pages/SearchPage.vue')
const { useQueryStateStore } = await import('@/stores/query-state')

const ANSWER = {
  events: [
    { analysis_id: 3, event: eventFixture({ id: 'a', summary: 'cmd.exe wrote C:\\a.ps1' }) },
    { analysis_id: 12, event: eventFixture({ id: 'b', summary: 'cmd.exe started powershell.exe' }) },
  ],
  total: 2,
  next_cursor: null,
}

async function mountSearch() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/search', component: SearchPage },
      { path: '/analyses/:id/:tab?', component: { template: '<div />' } },
    ],
  })
  await router.push('/search')
  await router.isReady()
  const wrapper = mount(SearchPage, {
    attachTo: document.body,
    global: { plugins: [Quasar, pinia, router] },
  })
  await flushPromises()
  return { wrapper, query: useQueryStateStore() }
}

async function applyQuery(query: ReturnType<typeof useQueryStateStore>, text: string) {
  query.setText(text)
  await flushPromises()
}

beforeEach(() => {
  document.body.innerHTML = ''
  searchAcrossAnalysesMock.mockReset()
})

afterEach(() => window.localStorage.clear())

describe('SearchPage', () => {
  it('asks the user for a query and sends no request before one is applied', async () => {
    const { wrapper } = await mountSearch()
    expect(wrapper.text()).toContain(t('search.hint'))
    expect(searchAcrossAnalysesMock).not.toHaveBeenCalled()
  })

  it('lists the events of every analysis, each with a link to its analysis', async () => {
    searchAcrossAnalysesMock.mockResolvedValue({ data: ANSWER, error: undefined, response: { status: 200 } })
    const { wrapper, query } = await mountSearch()
    await applyQuery(query, 'process.name:cmd.exe')
    expect(searchAcrossAnalysesMock).toHaveBeenCalledWith(
      expect.objectContaining({ body: expect.objectContaining({ query: 'process.name:cmd.exe' }) }),
    )
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(2)
    expect(wrapper.find('a[href="/analyses/3"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/analyses/12"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(t('search.table.analysis'))
  })

  it('says no event matches when the search finds nothing', async () => {
    searchAcrossAnalysesMock.mockResolvedValue({
      data: { events: [], total: 0, next_cursor: null },
      error: undefined,
      response: { status: 200 },
    })
    const { wrapper, query } = await mountSearch()
    await applyQuery(query, 'process.name:nothing')
    expect(wrapper.text()).toContain(t('events.table.noMatch'))
  })

  it('names the failure and retries the same search', async () => {
    searchAcrossAnalysesMock
      .mockResolvedValueOnce({ data: undefined, error: { error: { message: 'opensearch is down' } }, response: { status: 502 } })
      .mockResolvedValueOnce({ data: ANSWER, error: undefined, response: { status: 200 } })
    const { wrapper, query } = await mountSearch()
    await applyQuery(query, 'process.name:cmd.exe')
    expect(wrapper.text()).toContain('opensearch is down')
    const retry = wrapper.findAll('button').find((button) => button.text() === t('common.retry'))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()
    expect(searchAcrossAnalysesMock).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(2)
  })

  it('shows the loading state while the first page is on its way', async () => {
    searchAcrossAnalysesMock.mockReturnValue(new Promise(() => undefined))
    const { wrapper, query } = await mountSearch()
    await applyQuery(query, 'process.name:cmd.exe')
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
  })

  it('goes back to the hint when the query is cleared', async () => {
    searchAcrossAnalysesMock.mockResolvedValue({ data: ANSWER, error: undefined, response: { status: 200 } })
    const { wrapper, query } = await mountSearch()
    await applyQuery(query, 'process.name:cmd.exe')
    await applyQuery(query, '')
    expect(wrapper.text()).toContain(t('search.hint'))
  })
})
