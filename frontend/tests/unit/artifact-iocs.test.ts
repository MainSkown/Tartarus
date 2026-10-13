import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArtifactIocs from '@/components/ArtifactIocs.vue'
import CopyButton from '@/components/CopyButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import { DROPPER_HASH, iocsViewFixture } from './artifacts-fixtures'

const viewsIocs = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ viewsIocs }))

async function mountIocs() {
  const wrapper = mount(ArtifactIocs, { global: { plugins: [Quasar] }, props: { analysisId: 45 } })
  await flushPromises()
  return wrapper
}

const rows = (wrapper: Awaited<ReturnType<typeof mountIocs>>) => wrapper.findAll('tbody tr')
const chips = (wrapper: Awaited<ReturnType<typeof mountIocs>>) => wrapper.findAll('.type-chip')

beforeEach(() => {
  viewsIocs.mockResolvedValue({ data: iocsViewFixture() })
})

describe('ArtifactIocs', () => {
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
    const wrapper = mount(ArtifactIocs, { global: { plugins: [Quasar] }, props: { analysisId: 45 } })
    expect(wrapper.find('.loader').exists()).toBe(true)
  })
})
