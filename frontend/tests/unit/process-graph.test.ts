import { describe, expect, it } from 'vitest'
import {
  flattenProcesses,
  graphStylesheet,
  injectionPeers,
  nodeLabel,
  nodeSize,
  processClock,
  processLifetime,
  readGraphColors,
  resolveSelection,
  severityClass,
  toGraphElements,
  toTreeNodes,
  type GraphColors,
} from '@/services/process-graph'
import { processNode, sampleTree } from './process-fixtures'

const ROOT_ID = '45:9708@2026-10-13T15:39:50.393Z'
const CHILD_ID = '45:2476@2026-10-13T15:39:50.393Z'

function ids(elements: { data: { id?: string } }[]): string[] {
  return elements.map((element) => element.data.id!)
}

describe('flattenProcesses', () => {
  it('lists every process depth first, parents before children', () => {
    const grandchild = processNode(3)
    const tree = [processNode(1, { children: [processNode(2, { children: [grandchild] }), processNode(4)] })]

    expect(flattenProcesses(tree).map((node) => node.pid)).toEqual([1, 2, 3, 4])
  })

  it('is empty for no processes', () => {
    expect(flattenProcesses([])).toEqual([])
  })
})

describe('nodeLabel', () => {
  it('is name and pid, with the worst severity and the detection count when there are detections', () => {
    const { roots } = sampleTree()
    expect(nodeLabel(roots[0]!)).toBe('benign.exe (9708)\nHIGH · 5')
  })

  it('is just name and pid without detections', () => {
    expect(nodeLabel(processNode(7, { name: 'calc.exe' }))).toBe('calc.exe (7)')
  })

  it('shortens a very long name, the details show it in full', () => {
    const label = nodeLabel(processNode(7, { name: `${'x'.repeat(60)}.exe` }))

    expect(label).toBe(`${'x'.repeat(27)}… (7)`)
  })

  it('falls back to the pid when the name is unknown', () => {
    expect(nodeLabel(processNode(7, { name: null }))).toBe('pid 7')
  })
})

describe('nodeSize', () => {
  it('fits the longest line and the number of lines of the label', () => {
    const one = nodeSize('calc.exe (7)')
    const two = nodeSize('benign.exe (9708)\nHIGH · 5')
    const long = nodeSize('a_much_longer_process_name.exe (31337)')

    expect(two.width).toBeGreaterThan(one.width)
    expect(two.height).toBeGreaterThan(one.height)
    expect(long.width).toBeGreaterThan(two.width)
    expect(long.height).toBe(one.height)
  })

  it('leaves room for the icon of the sample when asked to', () => {
    expect(nodeSize('calc.exe (7)', { icon: true }).width).toBeGreaterThan(nodeSize('calc.exe (7)').width)
    expect(nodeSize('calc.exe (7)', { icon: true }).height).toBe(nodeSize('calc.exe (7)').height)
  })
})

describe('severityClass', () => {
  it.each([
    ['critical', 'sev-critical'],
    ['high', 'sev-high'],
    ['medium', 'sev-medium'],
    ['low', 'sev-low'],
    ['info', 'sev-info'],
    [null, 'sev-none'],
  ] as const)('maps %s to %s', (severity, expected) => {
    expect(severityClass(severity)).toBe(expected)
  })
})

describe('toGraphElements', () => {
  const none = { injection: false, hosts: false }

  it('makes a node per process, styled by its severity, and a spawn edge per child', () => {
    const elements = toGraphElements(sampleTree().roots, none)

    const nodes = elements.filter((element) => element.group === 'nodes')
    expect(nodes.map((node) => node.data.id)).toEqual([ROOT_ID, CHILD_ID])
    expect(nodes[0]!.data).toMatchObject({ label: 'benign.exe (9708)\nHIGH · 5', ...nodeSize('benign.exe (9708)\nHIGH · 5', { icon: true }) })
    expect(nodes[1]!.data).toMatchObject(nodeSize('cmd.exe (2476)\nMEDIUM · 2'))
    expect(nodes[0]!.classes).toContain('sev-high')
    expect(nodes[1]!.classes).toContain('sev-medium')
    const edges = elements.filter((element) => element.group === 'edges')
    expect(edges).toHaveLength(1)
    expect(edges[0]!.data).toMatchObject({ source: nodes[0]!.data.id, target: nodes[1]!.data.id })
    expect(edges[0]!.classes).toContain('spawn')
  })

  it('marks only the first root as the sample', () => {
    const tree = [processNode(1), processNode(2)]
    const [first, second] = toGraphElements(tree, none).filter((element) => element.group === 'nodes')

    expect(first!.classes).toContain('sample-root')
    expect(second!.classes).not.toContain('sample-root')
  })

  it('adds injection edges to the target pid only when asked to', () => {
    const tree = [processNode(1, { injected_into: [2, 999] }), processNode(2)]

    expect(toGraphElements(tree, none).filter((element) => element.classes?.includes('injection'))).toEqual([])
    const withInjection = toGraphElements(tree, { injection: true, hosts: false })
    const injections = withInjection.filter((element) => element.classes?.includes('injection'))
    expect(injections).toHaveLength(1)
    expect(injections[0]!.data).toMatchObject({ source: tree[0]!.entity_id, target: tree[1]!.entity_id })
  })

  it('adds one host node per distinct host, shared by the processes that contacted it, only when asked to', () => {
    const tree = [
      processNode(1, { network_hosts: ['evil.example', '10.0.0.5'] }),
      processNode(2, { network_hosts: ['evil.example'] }),
    ]

    expect(toGraphElements(tree, none).some((element) => element.classes?.includes('host'))).toBe(false)
    const elements = toGraphElements(tree, { injection: false, hosts: true })
    const hosts = elements.filter((element) => element.group === 'nodes' && element.classes?.includes('host'))
    expect(hosts.map((host) => host.data.label)).toEqual(['evil.example', '10.0.0.5'])
    const networkEdges = elements.filter((element) => element.classes?.includes('network'))
    expect(networkEdges).toHaveLength(3)
    expect(new Set(ids(elements)).size).toBe(elements.length)
  })

  it('keeps two processes that reuse a pid apart', () => {
    const first = processNode(5, { entity_id: '45:5@a' })
    const second = processNode(5, { entity_id: '45:5@b' })

    expect(ids(toGraphElements([first, second], none))).toEqual(['45:5@a', '45:5@b'])
  })

  it('has no elements for no processes', () => {
    expect(toGraphElements([], { injection: true, hosts: true })).toEqual([])
  })
})

describe('resolveSelection', () => {
  const { roots } = sampleTree()

  it('keeps a selection that is still in the tree', () => {
    expect(resolveSelection(roots, roots[0]!.children[0]!.entity_id)).toBe(roots[0]!.children[0]!.entity_id)
  })

  it('falls back to the first root when nothing, or something unknown, is selected', () => {
    expect(resolveSelection(roots, undefined)).toBe(roots[0]!.entity_id)
    expect(resolveSelection(roots, 'gone')).toBe(roots[0]!.entity_id)
  })

  it('selects nothing in an empty tree', () => {
    expect(resolveSelection([], undefined)).toBeUndefined()
  })
})

describe('injectionPeers', () => {
  it('names the processes a process injected into and the ones that injected into it', () => {
    const tree = [
      processNode(1, { name: 'a.exe', injected_into: [2] }),
      processNode(2, { name: 'b.exe', injected_into: [3] }),
      processNode(3, { name: 'c.exe' }),
    ]

    expect(injectionPeers(tree, tree[1]!)).toEqual({
      into: [{ pid: 3, name: 'c.exe' }],
      from: [{ pid: 1, name: 'a.exe' }],
    })
  })

  it('still names a target the tree does not contain', () => {
    const tree = [processNode(1, { injected_into: [999] })]

    expect(injectionPeers(tree, tree[0]!).into).toEqual([{ pid: 999, name: null }])
  })
})

describe('processLifetime', () => {
  it.each([
    ['2026-10-13T15:39:50.393Z', '2026-10-13T15:39:51.706Z', '1.3s'],
    ['2026-10-13T15:39:50.000Z', '2026-10-13T15:41:20.000Z', '1m 30s'],
    ['2026-10-13T15:39:50.000Z', '2026-10-13T15:39:50.000Z', '0.0s'],
  ])('is %s to %s = %s', (start, end, expected) => {
    expect(processLifetime(processNode(1, { start, end }))).toBe(expected)
  })

  it('is unknown without both ends', () => {
    expect(processLifetime(processNode(1, { end: null }))).toBeNull()
    expect(processLifetime(processNode(1, { start: null }))).toBeNull()
  })
})

describe('processClock', () => {
  it('is the UTC time of day with milliseconds, to tell apart processes started in the same second', () => {
    expect(processClock('2026-10-13T15:39:50.393000Z')).toBe('15:39:50.393')
  })

  it('is a dash for no time', () => {
    expect(processClock(null)).toBe('–')
  })
})

describe('toTreeNodes', () => {
  it('mirrors the process tree, keyed by entity id', () => {
    const [root] = toTreeNodes(sampleTree().roots)

    expect(root).toMatchObject({ key: ROOT_ID, label: 'benign.exe (9708)' })
    expect(root!.children).toHaveLength(1)
    expect(root!.children![0]!.process.pid).toBe(2476)
  })
})

describe('graphStylesheet', () => {
  const colors: GraphColors = {
    background: '#0a0a0a',
    text: '#ffffff',
    border: '#38bdf888',
    primary: '#38bdf8',
    selected: '#7dd3fc',
    spawn: '#0369a1',
    network: '#9085e9',
    injection: '#f97316',
    severity: { info: '#a3a3a3', low: '#94a3b8', medium: '#eab308', high: '#f97316', critical: '#ef4444' },
    font: 'monospace',
  }
  const rule = (selector: string) => {
    const entry = graphStylesheet(colors).find((candidate) => candidate.selector === selector)
    return entry as unknown as { style: Record<string, unknown> }
  }

  it('borders a node in the colour of its severity', () => {
    expect(rule('node.sev-critical').style).toMatchObject({ 'border-color': '#ef4444' })
    expect(rule('node.sev-medium').style).toMatchObject({ 'border-color': '#eab308' })
  })

  it('draws injection edges dashed in the high colour and network edges dotted', () => {
    expect(rule('edge.injection').style).toMatchObject({ 'line-style': 'dashed', 'line-color': '#f97316' })
    expect(rule('edge.network').style).toMatchObject({ 'line-style': 'dotted', 'line-color': '#9085e9' })
  })

  it('highlights the selected node and dims the others', () => {
    expect(rule('node.selected').style).toMatchObject({ 'border-color': '#7dd3fc' })
    expect(rule('node.dimmed').style).toMatchObject({ opacity: 0.4 })
  })
})

describe('readGraphColors', () => {
  it('resolves the design tokens of an element, since a canvas cannot read var()', () => {
    const element = document.createElement('div')
    element.style.setProperty('--status-high', '#f97316')
    element.style.setProperty('--cat-network', '#9085e9')
    element.style.setProperty('--blue-light', '#7dd3fc')
    element.style.setProperty('--font-mono', 'monospace')
    document.body.append(element)

    const colors = readGraphColors(element)

    expect(colors.severity.high).toBe('#f97316')
    expect(colors.injection).toBe('#f97316')
    expect(colors.network).toBe('#9085e9')
    expect(colors.selected).toBe('#7dd3fc')
    expect(colors.font).toBe('monospace')
    element.remove()
  })
})
