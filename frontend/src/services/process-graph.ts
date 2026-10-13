import type { ElementDefinition, StylesheetJson } from 'cytoscape'
import type { ProcessNode, ProcessRef, Severity } from '@/api'
import { SEVERITIES, severityMeta } from '@/services/analysis-status'
import { formatDuration, secondsBetween } from '@/services/format-duration'

export interface GraphOptions {
  injection: boolean
  hosts: boolean
}

export interface TreeNode {
  key: string
  label: string
  process: ProcessNode
  children?: TreeNode[]
}

export interface GraphColors {
  background: string
  text: string
  border: string
  primary: string
  selected: string
  spawn: string
  network: string
  injection: string
  severity: Record<Severity, string>
  font: string
}

const SUB_MINUTE_SECONDS = 60
const LABEL_FONT_SIZE = 12
// Courier's advance is 0.6 em; cytoscape no longer sizes a node to its label.
const LABEL_CHAR_WIDTH = LABEL_FONT_SIZE * 0.6
const LABEL_LINE_HEIGHT = LABEL_FONT_SIZE * 1.4
const NODE_PADDING = 10
const HOST_SIZE = 22
const MAX_LABEL_NAME = 28
const ICON_SIZE = 14
const ICON_ROOM = 2 * (ICON_SIZE + 4)
const BUG_REPORT_ICON =
  'M20 8h-2.81c-.45-.78-1.07-1.45-1.82-1.96L17 4.41 15.59 3l-2.17 2.17C12.96 5.06 12.49 5 12 5s-.96.06-1.41.17L8.41 3 7 4.41l1.62 1.63C7.88 6.55 7.26 7.22 6.81 8H4v2h2.09c-.05.33-.09.66-.09 1v1H4v2h2v1c0 .34.04.67.09 1H4v2h2.81c1.04 1.79 2.97 3 5.19 3s4.15-1.21 5.19-3H20v-2h-2.09c.05-.33.09-.66.09-1v-1h2v-2h-2v-1c0-.34-.04-.67-.09-1H20V8zm-6 8h-4v-2h4v2zm0-4h-4v-2h4v2z'

export function flattenProcesses(roots: ProcessNode[]): ProcessNode[] {
  return roots.flatMap((node) => [node, ...flattenProcesses(node.children)])
}

function shortened(name: string | null): string | null {
  if (name === null || name.length <= MAX_LABEL_NAME) return name
  return `${name.slice(0, MAX_LABEL_NAME - 1)}…`
}

export function processTitle(process: { pid: number; name: string | null }): string {
  return process.name ? `${process.name} (${process.pid})` : `pid ${process.pid}`
}

export function nodeLabel(node: ProcessNode): string {
  const title = processTitle({ pid: node.pid, name: shortened(node.name) })
  if (node.max_severity === null || node.detection_count === 0) return title
  return `${title}\n${severityMeta(node.max_severity).label} · ${node.detection_count}`
}

export function nodeSize(label: string, { icon = false } = {}): { width: number; height: number } {
  const lines = label.split('\n')
  const longest = Math.max(...lines.map((line) => line.length))
  return {
    width: Math.ceil(longest * LABEL_CHAR_WIDTH) + 2 * NODE_PADDING + (icon ? ICON_ROOM : 0),
    height: Math.ceil(lines.length * LABEL_LINE_HEIGHT) + 2 * NODE_PADDING,
  }
}

export function severityClass(severity: Severity | null): string {
  return severity === null ? 'sev-none' : `sev-${severity}`
}

function hostId(host: string): string {
  return `host:${host}`
}

function processElements(roots: ProcessNode[]): ElementDefinition[] {
  const spawnEdges = (parent: ProcessNode): ElementDefinition[] =>
    parent.children.flatMap((child) => [
      {
        group: 'edges' as const,
        data: { id: `spawn:${parent.entity_id}>${child.entity_id}`, source: parent.entity_id, target: child.entity_id },
        classes: 'spawn',
      },
      ...spawnEdges(child),
    ])
  const nodes = flattenProcesses(roots).map((node) => ({
    group: 'nodes' as const,
    data: { id: node.entity_id, label: nodeLabel(node), ...nodeSize(nodeLabel(node), { icon: node === roots[0] }) },
    classes: [severityClass(node.max_severity), node === roots[0] ? 'sample-root' : ''].join(' ').trim(),
  }))
  return [...nodes, ...roots.flatMap(spawnEdges)]
}

function injectionElements(processes: ProcessNode[]): ElementDefinition[] {
  return processes.flatMap((source) =>
    source.injected_into.flatMap((pid) => {
      const target = processes.find((process) => process.pid === pid)
      if (!target) return []
      return [
        {
          group: 'edges' as const,
          data: { id: `inject:${source.entity_id}>${target.entity_id}`, source: source.entity_id, target: target.entity_id, label: 'inject' },
          classes: 'injection',
        },
      ]
    }),
  )
}

function hostElements(processes: ProcessNode[]): ElementDefinition[] {
  const hosts = [...new Set(processes.flatMap((process) => process.network_hosts))]
  const nodes = hosts.map((host) => ({
    group: 'nodes' as const,
    data: { id: hostId(host), label: host },
    classes: 'host',
  }))
  const edges = processes.flatMap((process) =>
    process.network_hosts.map((host) => ({
      group: 'edges' as const,
      data: { id: `net:${process.entity_id}>${hostId(host)}`, source: process.entity_id, target: hostId(host) },
      classes: 'network',
    })),
  )
  return [...nodes, ...edges]
}

export function toGraphElements(roots: ProcessNode[], options: GraphOptions): ElementDefinition[] {
  const processes = flattenProcesses(roots)
  return [
    ...processElements(roots),
    ...(options.injection ? injectionElements(processes) : []),
    ...(options.hosts ? hostElements(processes) : []),
  ]
}

export function resolveSelection(roots: ProcessNode[], selected: string | undefined): string | undefined {
  const known = flattenProcesses(roots).some((process) => process.entity_id === selected)
  return known ? selected : roots[0]?.entity_id
}

export function injectionPeers(roots: ProcessNode[], node: ProcessNode): { into: ProcessRef[]; from: ProcessRef[] } {
  const processes = flattenProcesses(roots)
  return {
    into: node.injected_into.map((pid) => ({ pid, name: processes.find((process) => process.pid === pid)?.name ?? null })),
    from: processes
      .filter((process) => process.injected_into.includes(node.pid))
      .map(({ pid, name }) => ({ pid, name })),
  }
}

export function processLifetime(node: ProcessNode): string | null {
  if (node.start === null || node.end === null) return null
  const seconds = secondsBetween(node.start, node.end)
  return seconds < SUB_MINUTE_SECONDS ? `${seconds.toFixed(1)}s` : formatDuration(seconds)
}

export function processClock(iso: string | null): string {
  if (iso === null) return '–'
  return new Date(iso).toISOString().slice(11, 23)
}

export function toTreeNodes(roots: ProcessNode[]): TreeNode[] {
  return roots.map((process) => ({
    key: process.entity_id,
    label: processTitle(process),
    process,
    children: process.children.length > 0 ? toTreeNodes(process.children) : undefined,
  }))
}

export function readGraphColors(element: Element): GraphColors {
  const style = getComputedStyle(element)
  const token = (name: string): string => style.getPropertyValue(name).trim()
  return {
    background: token('--dark-bg'),
    text: token('--text-white'),
    border: token('--border-secondary'),
    primary: token('--blue-primary'),
    selected: token('--blue-light'),
    spawn: token('--blue-dark'),
    network: token('--cat-network'),
    injection: token('--status-high'),
    severity: Object.fromEntries(
      SEVERITIES.map((severity) => [severity, token(severityMeta(severity).color)]),
    ) as Record<Severity, string>,
    font: token('--font-mono'),
  }
}

const svgDataUri = (path: string, fill: string): string =>
  `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path fill="${fill}" d="${path}"/></svg>`)}`

export function graphStylesheet(colors: GraphColors): StylesheetJson {
  const severityRules = (Object.keys(colors.severity) as Severity[]).map((severity) => ({
    selector: `node.${severityClass(severity)}`,
    style: { 'border-color': colors.severity[severity] },
  }))
  return [
    {
      selector: 'node',
      style: {
        shape: 'rectangle',
        width: 'data(width)',
        height: 'data(height)',
        'background-color': colors.background,
        'border-width': 2,
        'border-color': colors.border,
        label: 'data(label)',
        color: colors.text,
        'font-family': colors.font,
        'font-size': LABEL_FONT_SIZE,
        'text-wrap': 'wrap',
        'text-valign': 'center',
        'text-halign': 'center',
        'line-height': 1.4,
      },
    },
    ...severityRules,
    {
      selector: 'node.sample-root',
      style: {
        'border-color': colors.primary,
        'underlay-color': colors.primary,
        'underlay-opacity': 0.25,
        'underlay-padding': 6,
        'background-image': svgDataUri(BUG_REPORT_ICON, colors.primary),
        'background-width': `${ICON_SIZE}px`,
        'background-height': `${ICON_SIZE}px`,
        'background-position-x': '6px',
        'background-position-y': '50%',
        'background-clip': 'none',
        'background-fit': 'none',
      },
    },
    {
      selector: 'node.host',
      style: {
        shape: 'diamond',
        width: HOST_SIZE,
        height: HOST_SIZE,
        'border-color': colors.network,
        'font-size': 10,
        'text-valign': 'bottom',
        'text-margin-y': 6,
      },
    },
    {
      selector: 'node.selected',
      style: {
        'border-color': colors.selected,
        'underlay-color': colors.selected,
        'underlay-opacity': 0.35,
        'underlay-padding': 8,
      },
    },
    { selector: 'node.dimmed', style: { opacity: 0.4 } },
    {
      selector: 'edge',
      style: {
        width: 2,
        'curve-style': 'bezier',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 1,
        'font-family': colors.font,
        'font-size': 9,
        color: colors.text,
        'text-background-color': colors.background,
        'text-background-opacity': 1,
        'text-background-padding': '2px',
      },
    },
    { selector: 'edge.spawn', style: { 'line-color': colors.spawn, 'target-arrow-color': colors.spawn, 'curve-style': 'taxi', 'taxi-direction': 'downward' } },
    {
      selector: 'edge.injection',
      style: {
        'line-style': 'dashed',
        'line-color': colors.injection,
        'target-arrow-color': colors.injection,
        label: 'data(label)',
      },
    },
    {
      selector: 'edge.network',
      style: { 'line-style': 'dotted', 'line-color': colors.network, 'target-arrow-color': colors.network, 'target-arrow-shape': 'none' },
    },
  ]
}
