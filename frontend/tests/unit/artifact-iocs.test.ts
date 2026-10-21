import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArtifactIocs from '@/components/ArtifactIocs.vue'
import CopyButton from '@/components/CopyButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import { DROPPER_HASH, iocsViewFixture } from './artifacts-fixtures'
import { filterEventsPlugins } from './filter-events-plugins'

const { plugins, router, query } = await filterEventsPlugins()

const { viewsIocs, iocsAnalyses } = vi.hoisted(() => ({ viewsIocs: vi.fn(), iocsAnalyses: vi.fn() }))
vi.mock('@/api', () => ({ viewsIocs, iocsAnalyses }))

async function mountIocs() {
  const wrapper = mount(ArtifactIocs, { global: { plugins }, props: { analysisId: 45 } })
  await flushPromises()
  return wrapper
}

const rows = (wrapper: Awaited<ReturnType<typeof mountIocs>>) => wrapper.findAll('tbody tr')
const chips = (wrapper: Awaited<ReturnType<typeof mountIocs>>) => wrapper.findAll('.type-chip')

beforeEach(() => {
  viewsIocs.mockResolvedValue({ data: iocsViewFixture() })
  iocsAnalyses.mockResolvedValue({ data: [{ analysis_id: 45, count: 2 }], response: { status: 200 } })
})

describe('ArtifactIocs', () => {
  it('shows beside each indicator value how many analyses hold it', async () => {
    const wrapper = await mountIocs()
    expect(rows(wrapper)[1]!.find('.ioc-analyses__chip').text()).toBe('Seen in 1 analysis')
  })

  it('asks for the indicators of the analysis', async () => {
    await mountIocs()
    expect(viewsIocs).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
  })

  it('lists type, value, count, context and process of each indicator', async () => {
    const wrapper = await mountIocs()
    expect(wrapper.findAll('th').map((th) => th.text())).toEqual(['TYPE', 'VALUE', 'COUNT', 'CONTEXT', 'PROCESS'])
    expect(rows(wrapper)).toHaveLength(4)
    const domain = rows(wrapper)[1]!
    expect(domain.text()).toContain('domain')
    expect(domain.text()).toContain('tartarus-selftest.example')
    expect(domain.find('.cell-count').text()).toBe('2')
    expect(domain.text()).toContain('benign.exe resolved tartarus-selftest.example')
    expect(domain.findComponent(ProcessChip).props('process')).toEqual({ pid: 9708, name: 'benign.exe' })
  })

  it('has a copy button holding the whole value', async () => {
    const wrapper = await mountIocs()
    expect(rows(wrapper)[0]!.findComponent(CopyButton).props()).toEqual({ text: DROPPER_HASH, what: 'indicator' })
  })

  it('keeps a long value reachable through its title', async () => {
    const wrapper = await mountIocs()
    expect(rows(wrapper)[0]!.find('.cell-value').attributes('title')).toBe(DROPPER_HASH)
  })

  describe('type filter', () => {
    it('offers all indicators plus each type present, with its count', async () => {
      const wrapper = await mountIocs()
      expect(chips(wrapper).map((chip) => chip.text())).toEqual(['all 4', 'hash 1', 'domain 2', 'url 1'])
      expect(chips(wrapper)[0]!.attributes('aria-pressed')).toBe('true')
    })

    it('narrows the list to one type, and back to all', async () => {
      const wrapper = await mountIocs()
      await chips(wrapper)[2]!.trigger('click')
      expect(rows(wrapper).map((row) => row.find('.cell-value').text())).toEqual([
        'tartarus-selftest.example',
        'outlook.office.com',
      ])
      expect(chips(wrapper)[2]!.attributes('aria-pressed')).toBe('true')
      expect(chips(wrapper)[0]!.attributes('aria-pressed')).toBe('false')
      await chips(wrapper)[0]!.trigger('click')
      expect(rows(wrapper)).toHaveLength(4)
    })

    it('goes back to all when the chosen type is clicked again', async () => {
      const wrapper = await mountIocs()
      await chips(wrapper)[1]!.trigger('click')
      await chips(wrapper)[1]!.trigger('click')
      expect(rows(wrapper)).toHaveLength(4)
    })
  })

  it('notes the types whose list was cut short', async () => {
    viewsIocs.mockResolvedValue({ data: iocsViewFixture({ truncated_types: ['domain', 'url'] }) })
    const note = (await mountIocs()).find('.truncated-note')
    expect(note.text()).toContain('domain')
    expect(note.text()).toContain('url')
  })

  it('has no truncation note when nothing was cut', async () => {
    expect((await mountIocs()).find('.truncated-note').exists()).toBe(false)
  })

  it('reports how many indicators there are', async () => {
    expect((await mountIocs()).emitted('counted')).toEqual([[undefined], [4]])
  })

  it('says when there are no indicators', async () => {
    viewsIocs.mockResolvedValue({ data: iocsViewFixture({ iocs: [] }) })
    expect((await mountIocs()).text()).toContain('no indicators were extracted')
  })

  it('shows the backend error and reloads on retry', async () => {
    viewsIocs.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'index is down' } } })
    const wrapper = await mountIocs()
    expect(wrapper.text()).toContain('index is down')
    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()
    expect(rows(wrapper)).toHaveLength(4)
  })

  it('shows the loader until the answer arrives', () => {
    viewsIocs.mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(ArtifactIocs, { global: { plugins }, props: { analysisId: 45 } })
    expect(wrapper.find('.loader').exists()).toBe(true)
  })
})

describe('ArtifactIocs show events actions', () => {
  beforeEach(() => query.reset())

  const FILTERABLE: [string, string, string][] = [
    ['hash', 'file.hash.sha256', 'abc123'],
    ['domain', 'domain', 'c2.example'],
    ['ip', 'destination.ip', '203.0.113.9'],
    ['url', 'url.full', 'http://c2.example/a'],
    ['registry', 'registry.path', 'HKCU\\Software\\Run\\x'],
    ['file', 'file.path', 'C:\\Temp\\a.exe'],
  ]

  async function mountWith(iocs: { type: string; value: string }[]) {
    viewsIocs.mockResolvedValue({
      data: iocsViewFixture({ iocs: iocs.map((ioc) => ({ ...ioc, count: 1, context: 'ctx', source_event_ids: [], process: null })) as never }),
    })
    return mountIocs()
  }

  it.each(FILTERABLE)('filters a %s indicator on %s', async (type, field, value) => {
    const wrapper = await mountWith([{ type, value }])
    const button = wrapper.get('tbody tr [aria-label^="Show events"]')
    expect(button.attributes('aria-label')).toBe(`Show events with ${field}: ${value}`)
    await button.trigger('click')
    await flushPromises()
    expect(query.chips).toEqual([{ field, value, negate: false }])
    expect(router.currentRoute.value.params.tab).toBe('events')
  })

  it('has no button for a mutex', async () => {
    const wrapper = await mountWith([{ type: 'mutex', value: 'Global\\x' }])
    expect(wrapper.find('tbody tr [aria-label^="Show events"]').exists()).toBe(false)
    expect(wrapper.find('tbody tr [aria-label="Copy indicator"]').exists()).toBe(true)
  })
})
