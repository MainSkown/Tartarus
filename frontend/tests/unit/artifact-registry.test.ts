import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArtifactRegistry from '@/components/ArtifactRegistry.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import { registryViewFixture } from './artifacts-fixtures'

const viewsRegistry = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ viewsRegistry }))

async function mountRegistry() {
  const wrapper = mount(ArtifactRegistry, { global: { plugins: [Quasar] }, props: { analysisId: 45 } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  viewsRegistry.mockResolvedValue({ data: registryViewFixture() })
})

describe('ArtifactRegistry', () => {
  it('asks for the registry changes of the analysis', async () => {
    await mountRegistry()
    expect(viewsRegistry).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
  })

  it('groups the changes by key, with the hive and the number of changes', async () => {
    const wrapper = await mountRegistry()
    const summaries = wrapper.findAll('summary').map((summary) => summary.text())
    expect(summaries).toEqual([
      expect.stringContaining('HKCU\\Software\\Tartarus'),
      expect.stringContaining('HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'),
    ])
    expect(summaries[0]).toContain('2')
  })

  it('lists action, value, type, data, process and time for each change', async () => {
    const wrapper = await mountRegistry()
    const group = wrapper.findAll('details')[0]!
    expect(group.findAll('th').map((th) => th.text())).toEqual(['ACTION', 'VALUE', 'TYPE', 'DATA', 'PROCESS', 'TIME'])
    const row = group.findAll('tbody tr')[1]!
    expect(row.text()).toContain('reg-value-set')
    expect(row.text()).toContain('SelfTest')
    expect(row.text()).toContain('REG_SZ')
    expect(row.text()).toContain('benign')
    expect(row.findComponent(ProcessChip).props('process')).toEqual({ pid: 9708, name: 'benign.exe' })
    expect(row.text()).toContain('2026-10-13 15:39:52 UTC')
  })

  it('shows a dash where a change has no value name or data', async () => {
    const wrapper = await mountRegistry()
    const keyCreated = wrapper.findAll('details')[0]!.findAll('tbody tr')[0]!
    expect(keyCreated.findAll('td').map((td) => td.text()).slice(1, 4)).toEqual(['–', '–', '–'])
  })

  it('opens the groups by default while there are few keys', async () => {
    const wrapper = await mountRegistry()
    expect(wrapper.findAll('details[open]')).toHaveLength(2)
  })

  it('starts with every group folded when there are many keys', async () => {
    const key = registryViewFixture().keys[0]!
    const keys = Array.from({ length: 12 }, (_, index) => ({ ...key, key: `Software\\K${index}` }))
    viewsRegistry.mockResolvedValue({ data: { keys, total: 24 } })
    const wrapper = await mountRegistry()
    expect(wrapper.findAll('details[open]')).toHaveLength(0)
  })

  it('reports how many changes there are', async () => {
    const wrapper = await mountRegistry()
    expect(wrapper.emitted('counted')).toEqual([[undefined], [3]])
  })

  it('says when no key was changed', async () => {
    viewsRegistry.mockResolvedValue({ data: { keys: [], total: 0 } })
    const wrapper = await mountRegistry()
    expect(wrapper.text()).toContain('no registry changes were recorded')
  })

  it('shows the backend error and reloads on retry', async () => {
    viewsRegistry.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'index is down' } } })
    const wrapper = await mountRegistry()
    expect(wrapper.text()).toContain('index is down')
    await wrapper.find('.retry-btn').trigger('click')
    await flushPromises()
    expect(viewsRegistry).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('details')).toHaveLength(2)
  })

  it('shows the loader until the answer arrives', () => {
    viewsRegistry.mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(ArtifactRegistry, { global: { plugins: [Quasar] }, props: { analysisId: 45 } })
    expect(wrapper.find('.loader').exists()).toBe(true)
  })
})
