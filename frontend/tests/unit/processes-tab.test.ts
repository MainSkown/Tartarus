import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { instances } from './cytoscape-mock'
import { analysisFixture } from './analysis-fixtures'
import { processDetail, processNode, sampleTree } from './process-fixtures'
import type { ProcessNode } from '@/api'

const viewsProcessesMock = vi.fn()
const viewsProcessMock = vi.fn()
vi.mock('@/api', () => ({
  viewsProcesses: (...args: unknown[]) => viewsProcessesMock(...args),
  viewsProcess: (...args: unknown[]) => viewsProcessMock(...args),
}))
vi.mock('cytoscape', async () => {
  const { createCytoscape } = await import('./cytoscape-mock')
  return { default: Object.assign(createCytoscape, { use: vi.fn() }) }
})
vi.mock('cytoscape-dagre', () => ({ default: {} }))

const { default: ProcessesTab } = await import('@/components/tabs/ProcessesTab.vue')

const tree = sampleTree()
const ROOT = tree.roots[0]!.entity_id
const CHILD = tree.roots[0]!.children[0]!.entity_id

async function mountTab() {
  const wrapper = mount(ProcessesTab, {
    attachTo: document.body,
    global: { plugins: [Quasar] },
    props: { analysis: analysisFixture({ id: 45 }) },
  })
  await flushPromises()
  return wrapper
}

function findProcess(pid: number, nodes: ProcessNode[] = tree.roots): ProcessNode {
  for (const node of nodes) {
    if (node.pid === pid) return node
    const found = node.children.length > 0 ? findProcess(pid, node.children) : undefined
    if (found) return found
  }
  throw new Error(`no pid ${pid}`)
}

function titleOfDetails(wrapper: Awaited<ReturnType<typeof mountTab>>): string {
  return wrapper.get('.process-details__title').text()
}

beforeEach(() => {
  instances.length = 0
  document.body.innerHTML = ''
  viewsProcessesMock.mockReset()
  viewsProcessesMock.mockResolvedValue({ data: tree })
  viewsProcessMock.mockReset()
  viewsProcessMock.mockImplementation(async ({ path }: { path: { pid: number } }) => ({
    data: processDetail(findProcess(path.pid)),
  }))
})

describe('ProcessesTab states', () => {
  it('keeps the data-tab marker of the tab registry', async () => {
    expect((await mountTab()).find('[data-tab="processes"]').exists()).toBe(true)
  })

  it('shows the loader while the processes load, for the analysis shown', async () => {
    viewsProcessesMock.mockReturnValue(new Promise(() => undefined))
    const wrapper = mount(ProcessesTab, { global: { plugins: [Quasar] }, props: { analysis: analysisFixture({ id: 45 }) } })

    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(viewsProcessesMock).toHaveBeenCalledWith({ path: { analysis_id: 45 } })
    expect(instances).toHaveLength(0)
  })

  it('shows the error and reloads on retry', async () => {
    viewsProcessesMock.mockResolvedValueOnce({ error: { error: { message: 'index is down' } } })
    const wrapper = await mountTab()
    expect(wrapper.text()).toContain('failed to load: index is down')

    await wrapper.get('.retry-btn').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('failed to load')
    expect(wrapper.find('.process-details').exists()).toBe(true)
  })

  it('says so when no process was recorded', async () => {
    viewsProcessesMock.mockResolvedValue({ data: { roots: [], total: 0 } })
    const wrapper = await mountTab()

    expect(wrapper.text()).toContain('> no processes recorded')
    expect(wrapper.find('.process-details').exists()).toBe(false)
    expect(instances).toHaveLength(0)
  })
})

describe('ProcessesTab loaded', () => {
  it('draws the graph with the first root selected and its details beside it', async () => {
    const wrapper = await mountTab()

    expect(instances).toHaveLength(1)
    expect(instances[0]!.hasClass(ROOT, 'selected')).toBe(true)
    expect(titleOfDetails(wrapper)).toBe('benign.exe (9708)')
    expect(viewsProcessMock).toHaveBeenCalledWith({ path: { analysis_id: 45, pid: 9708 } })
  })

  it('shows how many processes were recorded', async () => {
    expect((await mountTab()).text()).toContain('2 PROCESSES')
  })

  it('shows the details of a process selected in the graph, and loads its detail', async () => {
    const wrapper = await mountTab()

    instances[0]!.tap(CHILD)
    await flushPromises()

    expect(titleOfDetails(wrapper)).toBe('cmd.exe (2476)')
    expect(viewsProcessMock).toHaveBeenCalledWith({ path: { analysis_id: 45, pid: 2476 } })
    expect(instances[0]!.hasClass(CHILD, 'selected')).toBe(true)
  })

  it('names the processes a process injected into', async () => {
    const injector = processNode(1, { name: 'dropper.exe', injected_into: [2] })
    viewsProcessesMock.mockResolvedValue({ data: { roots: [injector, processNode(2, { name: 'explorer.exe' })], total: 2 } })
    viewsProcessMock.mockResolvedValue({ data: processDetail(injector) })
    const wrapper = await mountTab()

    expect(wrapper.text()).toContain('explorer.exe (2)')
  })
})

describe('ProcessesTab graph and tree', () => {
  function switchTo(wrapper: Awaited<ReturnType<typeof mountTab>>, label: string) {
    return wrapper.findAll('.q-btn-toggle button').find((button) => button.text() === label)!.trigger('click')
  }

  it('shows the graph by default', async () => {
    const wrapper = await mountTab()

    expect(wrapper.find('.process-graph').exists()).toBe(true)
    expect(wrapper.find('.process-tree-list').exists()).toBe(false)
  })

  it('switches to the tree of the same processes, keeping the graph out of the page', async () => {
    const wrapper = await mountTab()

    await switchTo(wrapper, 'TREE')

    expect(wrapper.find('.process-tree-list').exists()).toBe(true)
    expect(wrapper.find('.process-graph').exists()).toBe(false)
    expect(instances[0]!.destroy).toHaveBeenCalled()
    expect(wrapper.findAll('.q-tree__node-header')).toHaveLength(2)
  })

  it('selects a process from a tree row and keeps it selected back in the graph', async () => {
    const wrapper = await mountTab()
    await switchTo(wrapper, 'TREE')

    await wrapper.findAll('.q-tree__node-header')[1]!.trigger('click')
    await flushPromises()
    expect(titleOfDetails(wrapper)).toBe('cmd.exe (2476)')

    await switchTo(wrapper, 'GRAPH')
    expect(instances.at(-1)!.hasClass(CHILD, 'selected')).toBe(true)
  })
})
