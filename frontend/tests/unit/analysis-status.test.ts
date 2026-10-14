import { describe, expect, it } from 'vitest'
import type { AnalysisStatus, Severity } from '@/api'
import {
  ANALYSIS_STATUSES,
  SEVERITIES,
  analysisStatusMeta,
  compareSeverity,
  canReingest,
  isActiveStatus,
  isTerminalStatus,
  severityMeta,
} from '@/services/analysis-status'

// Typed as a Record so the test stops compiling when the backend adds a status or severity.
const EXPECTED_STATUSES: Record<AnalysisStatus, true> = {
  queued: true,
  starting: true,
  running: true,
  processing: true,
  ingesting: true,
  done: true,
  failed: true,
  report_failed: true,
  cancelled: true,
}
const EXPECTED_SEVERITIES: Record<Severity, true> = { info: true, low: true, medium: true, high: true, critical: true }

const ACTIVE: AnalysisStatus[] = ['starting', 'running', 'processing', 'ingesting']
const TERMINAL: AnalysisStatus[] = ['done', 'failed', 'report_failed', 'cancelled']

describe('analysis status metadata', () => {
  it('covers exactly the statuses the API defines', () => {
    expect([...ANALYSIS_STATUSES].sort()).toEqual(Object.keys(EXPECTED_STATUSES).sort())
  })

  it.each(ANALYSIS_STATUSES)('%s has an uppercase label, a colour token and an icon', (status) => {
    const meta = analysisStatusMeta(status)
    expect(meta.label).toMatch(/^[A-Z][A-Z ]*$/)
    expect(meta.color).toMatch(/^--[a-z-]+$/)
    expect(meta.icon).toMatch(/^[a-z_]+$/)
  })

  it('treats exactly starting, running, processing and ingesting as active', () => {
    expect(ANALYSIS_STATUSES.filter(isActiveStatus).sort()).toEqual([...ACTIVE].sort())
  })

  it('treats exactly done, failed, report_failed and cancelled as terminal', () => {
    expect(ANALYSIS_STATUSES.filter(isTerminalStatus).sort()).toEqual([...TERMINAL].sort())
  })

  it.each(ANALYSIS_STATUSES)('%s is exactly one of queued, active or terminal', (status) => {
    const kinds = [status === 'queued', isActiveStatus(status), isTerminalStatus(status)]
    expect(kinds.filter(Boolean)).toHaveLength(1)
  })

  it('uses the red token for failures, success green for done and a muted one for cancelled', () => {
    expect(analysisStatusMeta('failed').color).toBe('--status-critical')
    expect(analysisStatusMeta('report_failed').color).toBe('--status-critical')
    expect(analysisStatusMeta('done').color).toBe('--status-success')
    expect(analysisStatusMeta('cancelled').color).toBe('--text-gray-dark')
  })

  it('gives every status its own label', () => {
    const labels = ANALYSIS_STATUSES.map((status) => analysisStatusMeta(status).label)
    expect(new Set(labels).size).toBe(labels.length)
  })
})

describe('severity metadata', () => {
  it('covers exactly the severities the API defines, lowest first', () => {
    expect([...SEVERITIES].sort()).toEqual(Object.keys(EXPECTED_SEVERITIES).sort())
    expect(SEVERITIES).toEqual(['info', 'low', 'medium', 'high', 'critical'])
  })

  it.each(SEVERITIES)('%s has an uppercase label, a colour token and an icon', (severity) => {
    const meta = severityMeta(severity)
    expect(meta.label).toMatch(/^[A-Z]+$/)
    expect(meta.color).toMatch(/^--[a-z-]+$/)
    expect(meta.icon).toMatch(/^[a-z_]+$/)
  })

  it('follows the design system icons and tokens', () => {
    expect(severityMeta('critical')).toMatchObject({ icon: 'dangerous', color: '--status-critical' })
    expect(severityMeta('high')).toMatchObject({ icon: 'warning', color: '--status-high' })
    expect(severityMeta('medium')).toMatchObject({ icon: 'report', color: '--status-medium' })
    expect(severityMeta('low')).toMatchObject({ icon: 'info', color: '--status-low' })
    expect(severityMeta('info')).toMatchObject({ icon: 'info_outline', color: '--status-info' })
  })

  it('orders severities from info up to critical', () => {
    const shuffled: Severity[] = ['high', 'info', 'critical', 'low', 'medium']
    expect([...shuffled].sort(compareSeverity)).toEqual(['info', 'low', 'medium', 'high', 'critical'])
    expect(compareSeverity('critical', 'high')).toBeGreaterThan(0)
    expect(compareSeverity('low', 'low')).toBe(0)
  })
})

describe('canReingest', () => {
  it.each(ANALYSIS_STATUSES)('is %s: only a done or report_failed analysis can be re-ingested', (status) => {
    expect(canReingest(status)).toBe(status === 'done' || status === 'report_failed')
  })
})
