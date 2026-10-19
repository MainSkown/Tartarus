import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Artifact, MemorySummary } from '@/api'
import { artifactFixture } from './artifacts-fixtures'
import { eventPage } from './events-fixtures'
import { filterEventsPlugins } from './filter-events-plugins'
import { findingDetail, findingEvent, hollowEvent, memorySummary } from './memory-fixtures'

const api = vi.hoisted(() => ({ eventsSearch: vi.fn(), eventsDetail: vi.fn() }))
vi.mock('@/api', () => api)

const { default: ArtifactMemory } = await import('@/components/ArtifactMemory.vue')
const { plugins } = await filterEventsPlugins()

const DUMP: Artifact = artifactFixture({ id: 'mem1', name: 'memory.dmp', size: 4 * 1024 ** 3, guest_path: null, source_process: null })

interface Props {
  memory?: MemorySummary | null
  dump?: Artifact | null
  artifactsLoading?: boolean
  artifactsError?: string
}

async function mountMemory({ memory = memorySummary(), dump = null, ...rest }: Props = {}) {
  const wrapper = mount(ArtifactMemory, { global: { plugins }, props: { analysisId: 45, memory, dump, artifactsLoading: false, ...rest } })
  await flushPromises()
  return wrapper
}

type Memory = Awaited<ReturnType<typeof mountMemory>>

const groupTitles = (wrapper: Memory) => wrapper.findAll('.finding-group__name').map((name) => name.text())
const rowsOf = (wrapper: Memory) => wrapper.findAll('tr.finding-row')

function manyFindings(count: number) {
  return Array.from({ length: count }, (_, index) => findingEvent(`a${index.toString(16).padStart(4, '0')}`))
}

beforeEach(() => {
  api.eventsSearch.mockReset()
  api.eventsDetail.mockReset()
  api.eventsSearch.mockResolvedValue({
    data: eventPage([findingEvent('a1'), hollowEvent('h1'), findingEvent('a2')]),
    response: { status: 200 },
  })
  api.eventsDetail.mockImplementation(async ({ path }: { path: { event_id: string } }) => ({
    data: findingDetail(findingEvent(path.event_id)),
    response: { status: 200 },
  }))
})

describe('ArtifactMemory: the dump', () => {
  it('shows a kept dump with its size, hash and a download', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ dump_deleted: null }), dump: DUMP })
    const dump = wrapper.find('.memory-dump')
    expect(dump.text()).toContain('taken, 4 GB')
    expect(dump.text()).toContain('kept')
    expect(dump.text()).toContain('4 GB')
    expect(dump.find('a.download-link').attributes('href')).toBe('/api/analyses/45/artifacts/mem1/download')
  })

  it('says that a dump deleted after the findings is not on disk, and how to keep one, instead of an empty download', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ dump_deleted: true }), dump: null })
    const dump = wrapper.find('.memory-dump')
    expect(dump.text()).toContain('taken, 4 GB')
    expect(dump.text()).toContain('deleted after the findings')
    expect(dump.text()).toContain('not on disk any more')
    expect(dump.text()).toContain('FULL MEMORY DUMP + VOLATILITY')
    expect(dump.find('a.download-link').exists()).toBe(false)
    expect(dump.find('table').exists()).toBe(false)
  })

  it('warns that a dump that could not be deleted may still be on the volume, and offers the file if it is there', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ dump_deleted: false }), dump: DUMP })
    expect(wrapper.find('.memory-dump__status--warn').text()).toContain('could not be deleted')
    expect(wrapper.find('.memory-dump').text()).toContain('may still be on the CAPE volume')
    expect(wrapper.find('.memory-dump a.download-link').exists()).toBe(true)
  })

  it('says that a kept dump the analysis no longer holds is gone', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ dump_deleted: null }), dump: null })
    expect(wrapper.find('.memory-dump').text()).toContain('The dump is no longer on disk')
  })

  it('shows the file as not kept when it cannot be downloaded', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ dump_deleted: null }), dump: { ...DUMP, downloadable: false } })
    expect(wrapper.find('.download-unavailable').text()).toBe('not kept')
  })

  it('says no dump was taken when CAPE took none', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ dump_taken: false, findings: 'unavailable', dump_bytes: null, dump_deleted: null }) })
    expect(wrapper.find('.memory-dump').text()).toContain('No dump was taken')
    expect(wrapper.find('.memory-dump table').exists()).toBe(false)
  })

  it('says that none was requested, and that the Submit dialog has the option, without a memory summary', async () => {
    const wrapper = await mountMemory({ memory: null, dump: null })
    const text = wrapper.text()
    expect(text).toContain('no memory dump was requested for this analysis')
    expect(text).toContain('FULL MEMORY DUMP + VOLATILITY')
    expect(text).toContain('Submit dialog')
    expect(wrapper.find('.memory-findings').exists()).toBe(false)
    expect(api.eventsSearch).not.toHaveBeenCalled()
  })

  it('shows a dump found on disk for an analysis that has no memory summary, as before', async () => {
    const wrapper = await mountMemory({ memory: null, dump: DUMP })
    expect(wrapper.find('.memory-dump a.download-link').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('no memory dump was requested')
    expect(wrapper.find('.memory-findings').exists()).toBe(false)
  })

  it('shows the loader while the artifacts load and their error with a retry when they fail', async () => {
    const loading = await mountMemory({ memory: null, artifactsLoading: true })
    expect(loading.find('.memory-dump .loader').exists()).toBe(true)
    const failed = await mountMemory({ memory: null, artifactsError: 'index is down' })
    expect(failed.find('.memory-dump').text()).toContain('index is down')
    await failed.find('.memory-dump .retry-btn').trigger('click')
    expect(failed.emitted('retry-artifacts')).toHaveLength(1)
  })

  it('needs no artifacts to say the dump was deleted', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ dump_deleted: true }), artifactsError: 'index is down' })
    expect(wrapper.find('.memory-dump').text()).toContain('deleted after the findings')
    expect(wrapper.find('.memory-dump').text()).not.toContain('index is down')
  })
})

describe('ArtifactMemory: the findings', () => {
  it('searches for the Volatility detections of the analysis', async () => {
    await mountMemory()
    expect(api.eventsSearch).toHaveBeenCalledTimes(1)
    expect(api.eventsSearch.mock.calls[0]![0].path).toEqual({ analysis_id: 45 })
  })

  it('groups them by plugin, malfind first, with the plain name, what it finds and the count', async () => {
    const wrapper = await mountMemory()
    expect(groupTitles(wrapper)).toEqual(['malfind', 'hollowprocesses'])
    const [malfind, hollow] = wrapper.findAll('.finding-group')
    expect(malfind!.find('.finding-group__count').text()).toBe('2 findings')
    expect(malfind!.find('.finding-group__help').text()).toContain('executable private memory regions')
    expect(malfind!.findAll('tr.finding-row')).toHaveLength(2)
    expect(hollow!.find('.finding-group__count').text()).toBe('1 finding')
    expect(hollow!.findAll('tr.finding-row')).toHaveLength(1)
  })

  it('shows a plugin it does not know as received, without help text', async () => {
    api.eventsSearch.mockResolvedValue({
      data: eventPage([findingEvent('a1', {}, { 'tartarus.memory.plugin': 'windows.vadinfo.VadInfo' })]),
      response: { status: 200 },
    })
    const wrapper = await mountMemory()
    expect(groupTitles(wrapper)).toEqual(['VadInfo'])
    expect(wrapper.find('.finding-group__help').exists()).toBe(false)
  })

  it('lists the first rows of a group of many and shows more on request, not hundreds at once', async () => {
    api.eventsSearch.mockResolvedValue({ data: eventPage(manyFindings(60)), response: { status: 200 } })
    const wrapper = await mountMemory()
    expect(wrapper.find('.finding-group__count').text()).toBe('60 findings')
    expect(rowsOf(wrapper)).toHaveLength(25)
    const more = wrapper.find('.finding-group__more')
    expect(more.text()).toBe('[SHOW 25 MORE]')
    await more.trigger('click')
    expect(rowsOf(wrapper)).toHaveLength(50)
    expect(wrapper.find('.finding-group__more').text()).toBe('[SHOW 10 MORE]')
    await wrapper.find('.finding-group__more').trigger('click')
    expect(rowsOf(wrapper)).toHaveLength(60)
    expect(wrapper.find('.finding-group__more').exists()).toBe(false)
  })

  it('opens the details of a finding, with the hex preview from the event detail', async () => {
    const wrapper = await mountMemory()
    await wrapper.find('.finding-toggle').trigger('click')
    await flushPromises()
    expect(api.eventsDetail).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.hex-row').text()).toContain('4d 5a')
  })

  it('shows a skeleton while loading', async () => {
    api.eventsSearch.mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(ArtifactMemory, { global: { plugins }, props: { analysisId: 45, memory: memorySummary(), dump: null, artifactsLoading: false } })
    await flushPromises()
    expect(wrapper.find('.memory-findings [aria-busy="true"]').exists()).toBe(true)
    expect(wrapper.find('tr.finding-row').exists()).toBe(false)
  })

  it('says, neutrally, that the dump was read and nothing was found', async () => {
    api.eventsSearch.mockResolvedValue({ data: eventPage([]), response: { status: 200 } })
    const wrapper = await mountMemory()
    expect(wrapper.find('.memory-findings').text()).toContain('Volatility3 read the dump and found no injected or hollowed processes')
    expect(wrapper.find('.finding-group').exists()).toBe(false)
  })

  it('shows the error of the events request with a retry that asks again', async () => {
    api.eventsSearch.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'OpenSearch is not answering' } }, response: { status: 502 } })
    const wrapper = await mountMemory()
    expect(wrapper.find('.memory-findings').text()).toContain('OpenSearch is not answering')
    await wrapper.find('.memory-findings .retry-btn').trigger('click')
    await flushPromises()
    expect(api.eventsSearch).toHaveBeenCalledTimes(2)
    expect(groupTitles(wrapper)).toEqual(['malfind', 'hollowprocesses'])
  })

  it('notes that the plugins that failed may leave the findings incomplete, with the error as received', async () => {
    const wrapper = await mountMemory({ memory: memorySummary({ error: 'windows.malware.hollowprocesses failed: exit 1' }) })
    expect(wrapper.find('.memory-findings__note').text()).toContain('windows.malware.hollowprocesses failed: exit 1')
    expect(groupTitles(wrapper)).toHaveLength(2)
  })

  it('says how many of the findings it shows when the index holds more than one request returns', async () => {
    api.eventsSearch.mockResolvedValue({ data: eventPage(manyFindings(3), { total: 900 }), response: { status: 200 } })
    const wrapper = await mountMemory()
    expect(wrapper.find('.memory-findings__note').text()).toContain('Showing 3 of 900 findings')
  })

  it('reports how many findings there are, for the sub-tab, once loaded', async () => {
    const wrapper = await mountMemory()
    expect(wrapper.emitted('counted')?.at(-1)).toEqual([3])
  })
})

describe('ArtifactMemory: no findings to read', () => {
  const unavailable = memorySummary({
    dump_taken: false,
    findings: 'unavailable',
    error: 'CAPE took no memory dump: the storage has 31.2 GB free, below its floor of 50 GB',
    dump_bytes: null,
    dump_deleted: null,
  })
  const failed = memorySummary({ findings: 'failed', error: 'volatility3 exited with status 1: unsatisfied requirement', dump_deleted: null })

  it('says there was no dump to read and gives the error as received, without asking for events', async () => {
    const wrapper = await mountMemory({ memory: unavailable })
    const findings = wrapper.find('.memory-findings')
    expect(findings.text()).toContain('no findings: there was no dump to read')
    expect(findings.text()).toContain('CAPE took no memory dump: the storage has 31.2 GB free, below its floor of 50 GB')
    expect(api.eventsSearch).not.toHaveBeenCalled()
    expect(wrapper.emitted('counted')?.at(-1)).toEqual([undefined])
  })

  it('says the findings failed, gives the error as received, and that the dump itself is still there', async () => {
    const wrapper = await mountMemory({ memory: failed, dump: DUMP })
    const findings = wrapper.find('.memory-findings')
    expect(findings.text()).toContain('findings failed')
    expect(findings.text()).toContain('volatility3 exited with status 1: unsatisfied requirement')
    expect(findings.text()).toContain('The dump itself is still there')
    expect(api.eventsSearch).not.toHaveBeenCalled()
  })

  it('does not claim the dump is there when it was deleted or cannot be downloaded', async () => {
    const deleted = await mountMemory({ memory: { ...failed, dump_deleted: true } })
    expect(deleted.find('.memory-findings').text()).not.toContain('still there')
    const gone = await mountMemory({ memory: failed, dump: { ...DUMP, downloadable: false } })
    expect(gone.find('.memory-findings').text()).not.toContain('still there')
  })
})
