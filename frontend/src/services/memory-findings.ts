import type { Event, EventDetail, SearchRequest, Severity } from '@/api'
import { t, type MessageKey } from '@/i18n'
import { eventProcess } from '@/services/event-display'

/** The most one request returns; the Volatility normaliser reads far fewer rows than this per run in practice. */
export const MEMORY_FINDINGS_SIZE = 500

const PLUGIN_COLUMN = 'tartarus.memory.plugin'
const ADDRESS_COLUMN = 'tartarus.memory.address'
const PROTECTION_COLUMN = 'tartarus.memory.protection'
const NOTE_COLUMN = 'tartarus.memory.note'

const VOLATILITY_DATASET_PREFIX = 'volatility.'
const KNOWN_PLUGINS = ['malfind', 'hollowprocesses'] as const
const PLUGIN_HELP: Record<string, MessageKey> = {
  malfind: 'artifacts.memory.pluginHelp.malfind',
  hollowprocesses: 'artifacts.memory.pluginHelp.hollowprocesses',
}

export interface MemoryFinding {
  id: string
  plugin: string
  address: string | null
  protection: string | null
  note: string | null
  severity: Severity
  process: { pid: number; name: string | null } | null
}

export interface FindingGroup {
  plugin: string
  name: string
  findings: MemoryFinding[]
}

/**
 * The detection each finding raises, not the finding event next to it: the detection carries the
 * severity (the observation is always info) and shares the process and the `tartarus.memory.*`
 * fields. `tartarus.raw` is not a column the search can return, so the region preview comes from
 * the event's own document (`eventsDetail`).
 */
export function memoryFindingsRequest(): SearchRequest {
  return {
    filters: [
      { field: 'event.module', value: 'volatility' },
      { field: 'event.kind', value: 'alert' },
    ],
    lanes: ['memory'],
    size: MEMORY_FINDINGS_SIZE,
    columns: [PLUGIN_COLUMN, ADDRESS_COLUMN, PROTECTION_COLUMN, NOTE_COLUMN],
  }
}

function textField(event: Event, name: string): string | null {
  const value = event.fields[name]
  return typeof value === 'string' && value !== '' ? value : null
}

function pluginOf(event: Event): string {
  return textField(event, PLUGIN_COLUMN) ?? event.dataset?.replace(VOLATILITY_DATASET_PREFIX, '') ?? ''
}

export function findingFromEvent(event: Event): MemoryFinding {
  return {
    id: event.id,
    plugin: pluginOf(event),
    address: textField(event, ADDRESS_COLUMN),
    protection: textField(event, PROTECTION_COLUMN),
    note: textField(event, NOTE_COLUMN),
    severity: event.severity ?? 'info',
    process: eventProcess(event),
  }
}

/** `windows.malware.malfind` is shown as `malfind`, the name an analyst knows the plugin by. */
export function pluginName(plugin: string): string {
  return plugin.slice(plugin.lastIndexOf('.') + 1)
}

export function pluginHelp(name: string): string | undefined {
  const key = PLUGIN_HELP[name]
  return key === undefined ? undefined : t(key)
}

function knownRank(name: string): number {
  const rank = KNOWN_PLUGINS.findIndex((known) => known === name)
  return rank === -1 ? KNOWN_PLUGINS.length : rank
}

/** The groups of the plugins the app knows first, the others after them in the order they were received. */
export function groupFindings(findings: MemoryFinding[]): FindingGroup[] {
  const groups = new Map<string, FindingGroup>()
  for (const finding of findings) {
    const group = groups.get(finding.plugin) ?? { plugin: finding.plugin, name: pluginName(finding.plugin), findings: [] }
    group.findings.push(finding)
    groups.set(finding.plugin, group)
  }
  return [...groups.values()].sort((a, b) => knownRank(a.name) - knownRank(b.name))
}

export interface RegionPreview {
  hexdump: string | null
  disasm: string | null
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null
}

/** What Volatility printed of the region, kept whole as `tartarus.raw`; hollowprocesses reads no bytes, so it has none. */
export function regionPreview(source: EventDetail['source']): RegionPreview {
  const raw = (source.tartarus as { raw?: unknown } | undefined)?.raw
  const row = typeof raw === 'object' && raw !== null && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {}
  return { hexdump: text(row.Hexdump), disasm: text(row.Disasm) }
}

export function processCommandLine(source: EventDetail['source']): string | null {
  const commandLine = (source.process as { command_line?: unknown } | undefined)?.command_line
  return text(commandLine)
}
