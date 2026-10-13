import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProcessGraph from '@/components/ProcessGraph.vue'
import { fitting, instances, type FakeCytoscape } from './cytoscape-mock'
import { processNode, sampleTree } from './process-fixtures'
import type { ProcessNode } from '@/api'

vi.mock('cytoscape', async () => {
  const { createCytoscape } = await import('./cytoscape-mock')
  return { default: Object.assign(createCytoscape, { use: vi.fn() }) }
})
vi.mock('cytoscape-dagre', () => ({ default: {} }))

const { roots } = sampleTree()
const ROOT = roots[0]!.entity_id
const CHILD = roots[0]!.children[0]!.entity_id

function mountGraph(processes: ProcessNode[] = roots, selected: string | undefined = ROOT) {
  return mount(ProcessGraph, {
    attachTo: document.body,
    global: { plugins: [Quasar] },
    props: { roots: processes, selectedId: selected },
    slots: { 'toolbar-end': '<span class="extra">in the toolbar</span>' },
  })
}

function graph(): FakeCytoscape {
  return instances.at(-1)!
}

function button(wrapper: ReturnType<typeof mountGraph>, label: string) {
  return wrapper.get(`button[aria-label="${label}"]`)
}

function toggle(wrapper: ReturnType<typeof mountGraph>, label: string) {
  return wrapper.findAll('[role="switch"]').find((element) => element.text().includes(label))!
}

function edgeClasses(): string[] {
  return graph()
    .current.filter((element) => element.group === 'edges')
    .map((element) => String(element.classes))
}

beforeEach(() => {
  instances.length = 0
  fitting.zoom = 1
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ProcessGraph lifecycle', () => {
  it('creates the graph in its own container with a top-down dagre layout', () => {
    const wrapper = mountGraph()

    expect(instances).toHaveLength(1)
    expect(graph().options.container).toBe(wrapper.get('.process-graph__canvas').element)
    expect(graph().options.elements.filter((element) => element.group === 'nodes')).toHaveLength(2)
    expect(graph().layouts.at(-1)).toMatchObject({ name: 'dagre', rankDir: 'TB' })
  })

  it('destroys the graph when it unmounts', () => {
    const wrapper = mountGraph()
    const created = graph()

    wrapper.unmount()

    expect(created.destroy).toHaveBeenCalledOnce()
  })

  it('lays the graph out again when the processes change', async () => {
    const wrapper = mountGraph()
    const layouts = graph().layouts.length

    await wrapper.setProps({ roots: [processNode(1)], selectedId: undefined })

    expect(graph().current).toHaveLength(1)
    expect(graph().layouts.length).toBe(layouts + 1)
    expect(instances).toHaveLength(1)
  })
})

describe('ProcessGraph layout', () => {
  it('puts what the owner slots in at the end of the toolbar row', () => {
    const wrapper = mountGraph()

    expect(wrapper.get('.process-graph__toolbar .extra').text()).toBe('in the toolbar')
  })

  it('tells the graph when its canvas changes size', () => {
    const observed: { callback: () => void; element: Element }[] = []
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(private callback: () => void) {}
        observe(element: Element) {
          observed.push({ callback: this.callback, element })
        }
        disconnect() {}
      },
    )
    const wrapper = mountGraph()

    observed.find((entry) => entry.element === wrapper.get('.process-graph__canvas').element)!.callback()

    expect(graph().resize).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

describe('ProcessGraph fitting', () => {
  it('fits a large graph into the view', () => {
    fitting.zoom = 0.3
    mountGraph()

    expect(graph().fit).toHaveBeenCalled()
    expect(graph().level).toBe(0.3)
  })

  it('does not blow a small graph up beyond its natural size', () => {
    fitting.zoom = 3
    mountGraph()

    expect(graph().level).toBe(1)
    expect(graph().center).toHaveBeenCalled()
  })
})

describe('ProcessGraph selection', () => {
  it('highlights the selected process and dims the others', () => {
    mountGraph()

    expect(graph().hasClass(ROOT, 'selected')).toBe(true)
    expect(graph().hasClass(ROOT, 'dimmed')).toBe(false)
    expect(graph().hasClass(CHILD, 'dimmed')).toBe(true)
  })

  it('follows the selected id', async () => {
    const wrapper = mountGraph()

    await wrapper.setProps({ selectedId: CHILD })

    expect(graph().hasClass(CHILD, 'selected')).toBe(true)
    expect(graph().hasClass(ROOT, 'dimmed')).toBe(true)
  })

  it('asks for the process that was tapped', () => {
    const wrapper = mountGraph()

    graph().tap(CHILD)

    expect(wrapper.emitted('select')).toEqual([[CHILD]])
  })
})

describe('ProcessGraph toolbar', () => {
  it('fits the graph into the view', async () => {
    const wrapper = mountGraph()

    await button(wrapper, 'Fit graph to view').trigger('click')

    expect(graph().fit).toHaveBeenCalled()
  })

  it('zooms in and out around the middle of the view', async () => {
    const wrapper = mountGraph()

    await button(wrapper, 'Zoom in').trigger('click')
    const zoomedIn = graph().level
    await button(wrapper, 'Zoom out').trigger('click')

    expect(zoomedIn).toBeGreaterThan(1)
    expect(graph().level).toBeCloseTo(1)
  })

  it('resets the layout', async () => {
    const wrapper = mountGraph()
    const layouts = graph().layouts.length

    await button(wrapper, 'Reset layout').trigger('click')

    expect(graph().layouts.length).toBe(layouts + 1)
  })

  it('exports the whole graph as a PNG download', async () => {
    const wrapper = mountGraph()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    await button(wrapper, 'Export PNG').trigger('click')

    expect(graph().png).toHaveBeenCalledWith(expect.objectContaining({ full: true }))
    expect(click).toHaveBeenCalledOnce()
  })
})

describe('ProcessGraph toggles', () => {
  const injecting = [processNode(1, { injected_into: [2], network_hosts: ['evil.example'] }), processNode(2)]

  it('shows injection edges, and hides them when toggled off', async () => {
    const wrapper = mountGraph(injecting, undefined)
    expect(edgeClasses()).toContain('injection')

    await toggle(wrapper, 'INJECTION').trigger('click')

    expect(edgeClasses()).not.toContain('injection')
  })

  it('does not select a host node that was tapped', async () => {
    const wrapper = mountGraph(injecting, undefined)
    await toggle(wrapper, 'HOSTS').trigger('click')

    graph().tap('host:evil.example')

    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('adds the host nodes only once toggled on', async () => {
    const wrapper = mountGraph(injecting, undefined)
    expect(edgeClasses()).not.toContain('network')

    await toggle(wrapper, 'HOSTS').trigger('click')

    expect(edgeClasses()).toContain('network')
    expect(graph().hasClass('host:evil.example', 'host')).toBe(true)
  })
})
