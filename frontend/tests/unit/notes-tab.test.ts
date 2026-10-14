import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { annotations, failed, noteAnnotation, succeeded, tagAnnotation } from './annotation-fixtures'
import { analysisFixture } from './analysis-fixtures'
import { createMemoryHistory, createRouter } from 'vue-router'
import { processNode } from './process-fixtures'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/analyses/:id/:tab?', name: 'analysis-workspace', component: { render: () => null } }],
})

const annotationsReadMock = vi.fn()
const viewsProcessesMock = vi.fn()
vi.mock('@/api', () => ({
  annotationsRead: (...args: unknown[]) => annotationsReadMock(...args),
  viewsProcesses: (...args: unknown[]) => viewsProcessesMock(...args),
}))

const { default: NotesTab } = await import('@/components/tabs/NotesTab.vue')
const { default: NoteEditor } = await import('@/components/NoteEditor.vue')
const { ANALYSIS_TARGET, useAnnotationsStore } = await import('@/stores/annotations')
const { useQueryStateStore } = await import('@/stores/query-state')

const analysisTag = tagAnnotation({ tag: 'phishing' })
const analysisNote = noteAnnotation({ body: 'Looks like a phishing dropper.' })
const processTag = tagAnnotation({ tag: 'dropper', target_type: 'process', target_ref: '9708' })
const processNote = noteAnnotation({ target_type: 'process', target_ref: '9708', body: 'Spawns cmd.exe' })
const eventTag = tagAnnotation({ tag: 'c2', target_type: 'event', target_ref: '7a9f3c1e5b20d4a8' })
const eventNote = noteAnnotation({ target_type: 'event', target_ref: '7a9f3c1e5b20d4a8', body: 'Beacon every 30s' })
const goneEvent = noteAnnotation({ target_type: 'event', target_ref: 'deadbeefdeadbeef', body: 'old finding', orphaned: true })
const goneProcessTag = tagAnnotation({ tag: 'stale', target_type: 'process', target_ref: '31337', orphaned: true })

const FULL = annotations(
  [analysisTag, processTag, eventTag, goneProcessTag],
  [analysisNote, processNote, eventNote, goneEvent],
)

let query: ReturnType<typeof useQueryStateStore>
let store: ReturnType<typeof useAnnotationsStore>
let plugins: [typeof Quasar, typeof router, ReturnType<typeof createPinia>]

function mountBare() {
  return mount(NotesTab, { global: { plugins }, props: { analysis: analysisFixture({ id: 45 }) } })
}

async function mountTab(content = FULL) {
  annotationsReadMock.mockResolvedValue(succeeded(content))
  await store.ensureLoaded(45)
  const wrapper = mountBare()
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountTab>>

const entryFor = (wrapper: Wrapper, text: string) =>
  wrapper.findAll('.notes-entry').find((entry) => entry.text().includes(text))!

beforeEach(async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  plugins = [Quasar, router, pinia]
  query = useQueryStateStore()
  store = useAnnotationsStore()
  await router.replace('/analyses/45/notes?q=lane:file')
  viewsProcessesMock.mockReset().mockResolvedValue(succeeded({ roots: [processNode(9708, { name: 'benign.exe' })], total: 1 }))
  annotationsReadMock.mockReset()
})

describe('NotesTab', () => {
  it('keeps the marker of the tab registry', async () => {
    expect((await mountTab()).find('[data-tab="notes"]').exists()).toBe(true)
  })

  it('edits the note of the analysis at the top', async () => {
    const wrapper = await mountTab()
    const editor = wrapper.findComponent(NoteEditor)
    expect(editor.props()).toMatchObject({ target: ANALYSIS_TARGET, editable: true })
    expect(wrapper.get('textarea').element.value).toBe('Looks like a phishing dropper.')
  })

  it('groups the entries under the analysis, its processes and its events', async () => {
    const wrapper = await mountTab()
    const titles = wrapper.findAll('.notes-group__title')
    expect(titles.map((title) => title.text().replace(/\d+$/, '').trim())).toEqual(['ANALYSIS', 'PROCESSES', 'EVENTS'])
    expect(wrapper.findAll('.notes-group__count').map((count) => count.text())).toEqual(['2', '2'])
  })

  it('lists the tags of the analysis without repeating the note the editor shows', async () => {
    const wrapper = await mountTab()
    const entry = wrapper.get('.notes-group .notes-entry')
    expect(entry.findAll('.tag-chip').map((chip) => chip.text())).toEqual(['phishing'])
    expect(entry.text()).not.toContain('Looks like a phishing dropper.')
  })

  it('shows the tags and notes of a process under its name and pid', async () => {
    const entry = entryFor(await mountTab(), 'benign.exe (9708)')
    expect(entry.findAll('.tag-chip').map((chip) => chip.text())).toEqual(['dropper'])
    expect(entry.get('.notes-entry__note').text()).toBe('Spawns cmd.exe')
  })

  it('falls back to the bare pid when the process names cannot be read', async () => {
    viewsProcessesMock.mockResolvedValue({ error: { error: { message: 'down' } } })
    expect(entryFor(await mountTab(), 'pid 9708').exists()).toBe(true)
  })

  it('shows an event by the start of its id, with the whole id on hover', async () => {
    const entry = entryFor(await mountTab(), '7a9f3c1e')
    expect(entry.get('.notes-entry__link').text()).toBe('event 7a9f3c1e…')
    expect(entry.get('.notes-entry__link').attributes('title')).toBe('7a9f3c1e5b20d4a8')
    expect(entry.get('.notes-entry__note').text()).toBe('Beacon every 30s')
  })

  it('links a process to the Processes tab with that pid selected, keeping the query', async () => {
    const wrapper = await mountTab()
    await entryFor(wrapper, 'benign.exe (9708)').get('.notes-entry__link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.params).toEqual({ id: '45', tab: 'processes' })
    expect(router.currentRoute.value.query).toEqual({ q: 'lane:file', sel: '9708' })
  })

  it('links an event to the Events tab with the event open', async () => {
    const wrapper = await mountTab()
    await entryFor(wrapper, '7a9f3c1e').get('.notes-entry__link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.params).toEqual({ id: '45', tab: 'events' })
    expect(router.currentRoute.value.query).toMatchObject({ e: '7a9f3c1e5b20d4a8' })
    expect(query.eventId).toBe('7a9f3c1e5b20d4a8')
  })

  it('marks an annotation whose target is gone as orphaned and does not link it', async () => {
    const wrapper = await mountTab()
    for (const text of ['deadbeef', 'pid 31337']) {
      const entry = entryFor(wrapper, text)
      expect(entry.classes()).toContain('is-orphaned')
      expect(entry.get('.notes-entry__orphan').text()).toBe('ORPHANED')
      expect(entry.find('.notes-entry__link').exists()).toBe(false)
    }
    expect(entryFor(wrapper, 'deadbeef').get('.notes-entry__note').text()).toBe('old finding')
  })

  it('does not mark a live target as orphaned', async () => {
    const wrapper = await mountTab()
    expect(entryFor(wrapper, 'benign.exe (9708)').find('.notes-entry__orphan').exists()).toBe(false)
  })

  it('keeps long notes in a box of their own', async () => {
    const wrapper = await mountTab(
      annotations([], [noteAnnotation({ target_type: 'event', target_ref: 'e1', body: 'x'.repeat(20_000) })]),
    )
    expect(wrapper.get('.notes-entry__note').text()).toHaveLength(20_000)
  })
})

describe('NotesTab states', () => {
  it('says so, in the terminal voice, when there is nothing but the empty editor', async () => {
    const wrapper = await mountTab(annotations())
    expect(wrapper.text()).toContain('> no tags or notes yet')
    expect(wrapper.findComponent(NoteEditor).exists()).toBe(true)
    expect(wrapper.find('.notes-group').exists()).toBe(false)
  })

  it('shows the loader while the annotations load', async () => {
    annotationsReadMock.mockReturnValue(new Promise(() => undefined))
    void store.ensureLoaded(45)
    const wrapper = mountBare()
    expect(wrapper.find('.loader').exists()).toBe(true)
  })

  it('shows the failure and reads again on retry', async () => {
    annotationsReadMock.mockResolvedValue(failed('index is down', 500))
    await store.ensureLoaded(45)
    const wrapper = mountBare()
    expect(wrapper.text()).toContain('failed to load: index is down')

    annotationsReadMock.mockResolvedValue(succeeded(annotations([analysisTag])))
    await wrapper.get('.retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('failed to load')
    expect(wrapper.findAll('.tag-chip').map((chip) => chip.text())).toEqual(['phishing'])
  })
})
