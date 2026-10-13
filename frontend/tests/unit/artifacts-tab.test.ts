import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArtifactTable from '@/components/ArtifactTable.vue'
import ArtifactsTab from '@/components/tabs/ArtifactsTab.vue'
import {
  ANALYSIS,
  artifactFixture,
  artifactsViewFixture,
  EMPTY_ARTIFACTS_VIEW,
  iocsViewFixture,
  registryViewFixture,
} from './artifacts-fixtures'

const api = vi.hoisted(() => ({ viewsArtifacts: vi.fn(), viewsRegistry: vi.fn(), viewsIocs: vi.fn() }))
vi.mock('@/api', () => api)

async function mountTab() {
  const wrapper = mount(ArtifactsTab, { global: { plugins: [Quasar] }, props: { analysis: ANALYSIS } })
  await flushPromises()
  return wrapper
}

type Tab = Awaited<ReturnType<typeof mountTab>>

const subTabs = (wrapper: Tab) => wrapper.findAll('.q-tab')
const subTabLabels = (wrapper: Tab) => subTabs(wrapper).map((tab) => tab.text())

async function open(wrapper: Tab, label: string): Promise<void> {
  const tab = subTabs(wrapper).find((candidate) => candidate.text().startsWith(label))
  if (!tab) throw new Error(`no sub-tab ${label}`)
  await tab.trigger('click')
  await flushPromises()
}

const visiblePanel = (wrapper: Tab) => wrapper.find('.artifact-panel:not([style*="display: none"])')

beforeEach(() => {
  api.viewsArtifacts.mockResolvedValue({ data: artifactsViewFixture() })
  api.viewsRegistry.mockResolvedValue({ data: registryViewFixture() })
  api.viewsIocs.mockResolvedValue({ data: iocsViewFixture() })
})

describe('ArtifactsTab', () => {
  it('keeps the marker the page tests look for', async () => {
    expect((await mountTab()).find('[data-tab="artifacts"]').exists()).toBe(true)
  })

  it('asks for the artifacts of the analysis', async () => {
    await mountTab()
    expect(api.viewsArtifacts).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
  })

  it('starts on the dropped files', async () => {
    const wrapper = await mountTab()
    expect(wrapper.find('.q-tab--active').text()).toContain('DROPPED FILES')
    expect(visiblePanel(wrapper).text()).toContain('tartarus-benign.txt')
  })

  describe('sub-tab labels', () => {
    it('carry the counts known from the artifacts', async () => {
      api.viewsArtifacts.mockResolvedValue({
        data: artifactsViewFixture({
          dropped: [artifactFixture(), artifactFixture({ id: 'b' })],
          payloads: [artifactFixture({ id: 'c' })],
          memory_dump: artifactFixture({ id: 'd', name: 'memory.dmp' }),
        }),
      })
      const labels = subTabLabels(await mountTab())
      expect(labels.slice(0, 3)).toEqual(['DROPPED FILES (2)', 'PAYLOADS & CONFIGS (1)', 'PROCESS DUMPS (2)'])
    })

    it('have no count for registry and indicators until they are loaded', async () => {
      expect(subTabLabels(await mountTab()).slice(3)).toEqual(['REGISTRY', 'IOCs'])
    })

    it('show the registry and indicator counts once those sub-tabs have loaded', async () => {
      const wrapper = await mountTab()
      await open(wrapper, 'REGISTRY')
      await open(wrapper, 'IOCs')
      expect(subTabLabels(wrapper).slice(3)).toEqual(['REGISTRY (3)', 'IOCs (4)'])
    })

    it('have no counts while the artifacts load', () => {
      api.viewsArtifacts.mockReturnValue(new Promise(() => undefined))
      const wrapper = mount(ArtifactsTab, { global: { plugins: [Quasar] }, props: { analysis: ANALYSIS } })
      expect(subTabLabels(wrapper as unknown as Tab)[0]).toBe('DROPPED FILES')
    })
  })

  describe('lazy loading', () => {
    it('does not ask for the registry or the indicators before their sub-tabs are opened', async () => {
      await mountTab()
      expect(api.viewsRegistry).not.toHaveBeenCalled()
      expect(api.viewsIocs).not.toHaveBeenCalled()
    })

    it('asks for the registry when its sub-tab is opened, once', async () => {
      const wrapper = await mountTab()
      await open(wrapper, 'REGISTRY')
      await open(wrapper, 'DROPPED')
      await open(wrapper, 'REGISTRY')
      expect(api.viewsRegistry).toHaveBeenCalledTimes(1)
      expect(api.viewsIocs).not.toHaveBeenCalled()
    })

    it('asks for the indicators when their sub-tab is opened', async () => {
      const wrapper = await mountTab()
      await open(wrapper, 'IOCs')
      expect(api.viewsIocs).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
      expect(visiblePanel(wrapper).text()).toContain('tartarus-selftest.example')
    })
  })

  describe('dropped files', () => {
    it('lists them in the artifact table', async () => {
      const table = (await mountTab()).findComponent(ArtifactTable)
      expect(table.props('analysisId')).toBe(45)
      expect(table.props('artifacts')).toEqual(artifactsViewFixture().dropped)
      expect(table.props('showFamily')).toBeFalsy()
    })

    it('says when none were dropped', async () => {
      api.viewsArtifacts.mockResolvedValue({ data: EMPTY_ARTIFACTS_VIEW })
      expect((await mountTab()).text()).toContain('no files were dropped')
    })

    it('shows the loader while loading', () => {
      api.viewsArtifacts.mockReturnValue(new Promise(() => undefined))
      const wrapper = mount(ArtifactsTab, { global: { plugins: [Quasar] }, props: { analysis: ANALYSIS } })
      expect(wrapper.find('.loader').exists()).toBe(true)
    })

    it('shows the error with a retry that asks again', async () => {
      api.viewsArtifacts.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'index is down' } } })
      const wrapper = await mountTab()
      expect(wrapper.text()).toContain('index is down')
      await wrapper.find('.retry-btn').trigger('click')
      await flushPromises()
      expect(api.viewsArtifacts).toHaveBeenCalledTimes(2)
      expect(wrapper.findComponent(ArtifactTable).exists()).toBe(true)
    })
  })

  describe('payloads and configs', () => {
    const config = { id: 'cfg1', family: 'AgentTesla', data: { c2: ['http://evil.example/gate.php'], port: 443 } }

    async function openPayloads(view = artifactsViewFixture()) {
      api.viewsArtifacts.mockResolvedValue({ data: view })
      const wrapper = await mountTab()
      await open(wrapper, 'PAYLOADS')
      return wrapper
    }

    it('lists the payloads with their family', async () => {
      const wrapper = await openPayloads(
        artifactsViewFixture({ payloads: [artifactFixture({ cape_type: 'AgentTesla Payload' })] }),
      )
      const table = visiblePanel(wrapper).findComponent(ArtifactTable)
      expect(table.props('showFamily')).toBe(true)
      expect(table.text()).toContain('AgentTesla Payload')
    })

    it('prints each extracted config as key/value data in a code block under its family', async () => {
      const wrapper = await openPayloads(artifactsViewFixture({ configs: [config] }))
      const panel = visiblePanel(wrapper)
      expect(panel.find('.config-family').text()).toBe('AgentTesla')
      const code = panel.find('pre.code-block').text()
      expect(code).toContain('"c2": [')
      expect(code).toContain('"http://evil.example/gate.php"')
      expect(code).toContain('"port": 443')
    })

    it('shows a config even when no payload file was kept', async () => {
      const wrapper = await openPayloads(artifactsViewFixture({ configs: [config] }))
      expect(visiblePanel(wrapper).findComponent(ArtifactTable).exists()).toBe(false)
      expect(visiblePanel(wrapper).find('pre').exists()).toBe(true)
    })

    it('says when there are neither payloads nor configs', async () => {
      const wrapper = await openPayloads()
      expect(visiblePanel(wrapper).text()).toContain('no payloads or configs were extracted')
    })
  })

  describe('process dumps', () => {
    it('lists the process dumps', async () => {
      const wrapper = await mountTab()
      await open(wrapper, 'PROCESS DUMPS')
      const table = visiblePanel(wrapper).findComponent(ArtifactTable)
      expect(table.props('artifacts')).toEqual(artifactsViewFixture().procdumps)
    })

    it('adds the memory dump with its size and download when there is one', async () => {
      const memory = artifactFixture({ id: 'mem1', name: 'memory.dmp', size: 2147483648, guest_path: null })
      api.viewsArtifacts.mockResolvedValue({ data: artifactsViewFixture({ memory_dump: memory }) })
      const wrapper = await mountTab()
      await open(wrapper, 'PROCESS DUMPS')
      const panel = visiblePanel(wrapper)
      expect(panel.find('.memory-heading').exists()).toBe(true)
      const memoryTable = panel.findAllComponents(ArtifactTable)[1]!
      expect(memoryTable.text()).toContain('2 GB')
      expect(memoryTable.find('a.download-link').attributes('href')).toBe('/api/analyses/45/artifacts/mem1/download')
    })

    it('shows a memory dump alone when no process was dumped', async () => {
      api.viewsArtifacts.mockResolvedValue({
        data: artifactsViewFixture({ procdumps: [], memory_dump: artifactFixture({ name: 'memory.dmp' }) }),
      })
      const wrapper = await mountTab()
      await open(wrapper, 'PROCESS DUMPS')
      expect(visiblePanel(wrapper).findAllComponents(ArtifactTable)).toHaveLength(1)
      expect(visiblePanel(wrapper).text()).not.toContain('no process dumps')
    })

    it('says when nothing was dumped', async () => {
      api.viewsArtifacts.mockResolvedValue({ data: EMPTY_ARTIFACTS_VIEW })
      const wrapper = await mountTab()
      await open(wrapper, 'PROCESS DUMPS')
      expect(visiblePanel(wrapper).text()).toContain('no process or memory dumps were captured')
    })
  })

  it('shows the artifacts error in each of the sub-tabs that depend on it', async () => {
    api.viewsArtifacts.mockResolvedValue({ error: { error: { code: 'x', message: 'index is down' } } })
    const wrapper = await mountTab()
    for (const label of ['PAYLOADS', 'PROCESS DUMPS']) {
      await open(wrapper, label)
      expect(visiblePanel(wrapper).text()).toContain('index is down')
    }
  })
})
