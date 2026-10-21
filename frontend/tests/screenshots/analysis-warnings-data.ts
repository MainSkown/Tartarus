import type { AnalysisRead } from '../../src/api/types.gen'
import { makeDetectedAnalysis } from './fixtures'

export const ID = 47

export const SYSMON_WARNING = 'Sysmon events were not exported: the guest did not answer within 120 s'
export const DEFENDER_WARNING = 'Windows Defender events were not exported: the guest did not answer within 120 s'
export const LONG_WARNING = `Sysmon events were not exported: ${'the guest agent stopped answering while the sample was still spawning child processes, '.repeat(3)}and the export of C:\\ProgramData\\Microsoft\\Windows\\Sysmon\\${'nested_'.repeat(12)}events.evtx was abandoned`

/** A finished, detected analysis whose summary carries the given warnings (none when omitted, as an analysis read before the field existed). */
export function analysisWithWarnings(warnings?: string[]): AnalysisRead {
  const base = makeDetectedAnalysis({ id: ID, guest: 'lab5', guest_badges: ['DEFENDER ON', 'SYSMON'] })
  return { ...base, summary: { ...base.summary, ...(warnings === undefined ? {} : { warnings }) } }
}
