import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SeverityBadge from '@/components/SeverityBadge.vue'
import {
  analysisWithStatus,
  DETECTIONS_SUMMARY,
  NO_DETECTIONS_SUMMARY,
} from './analysis-fixtures'
import { ARTIFACTS_VIEW } from './detections-fixtures'
import type { AnalysisRead } from '@/api'

vi.mock('@/api', () => ({ viewsArtifacts: vi.fn() }))

const { viewsArtifacts } = await import('@/api')
const AnalysisSummaryTab = (await import('@/components/AnalysisSummaryTab.vue')).default
const artifactsMock = vi.mocked(viewsArtifacts)

beforeEach(() => {
  artifactsMock.mockResolvedValue({ data: ARTIFACTS_VIEW, error: undefined } as never)
})

function mountTab(analysis: AnalysisRead) {
  return mount(AnalysisSummaryTab, { global: { plugins: [Quasar] }, props: { analysis } })
}

describe('AnalysisSummaryTab waiting states', () => {
  it.each([
    [1, 'next in the queue'],
    [3, 'position 3 in the queue'],
  ])('says where queued position %i stands', (position, expected) => {
    const wrapper = mountTab(
      analysisWithStatus('queued', { started_at: null, finished_at: null, queue_position: position }),
    )
    expect(wrapper.text()).toContain(expected)
  })

  it('explains that a queued analysis is waiting for the guest', () => {
    const wrapper = mountTab(analysisWithStatus('queued', { started_at: null, finished_at: null }))
    expect(wrapper.text()).toContain('queued')
    expect(wrapper.text()).toContain('waiting')
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
  })

  it.each([
    ['starting', 'starting the guest'],
    ['running', 'detonating in the guest'],
    ['processing', 'CAPE is processing'],
    ['ingesting', 'reading the report'],
  ] as const)('shows progress and the phase for %s', (status, phase) => {
    const wrapper = mountTab(analysisWithStatus(status, { finished_at: null }))
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(phase)
  })
})

describe('AnalysisSummaryTab done', () => {
  const detected = () =>
    mountTab(
      analysisWithStatus('done', {
        score: 6,
        max_severity: 'high',
        detected_families: ['emotet'],
        summary: DETECTIONS_SUMMARY,
      }),
    )

  it('shows the score, the highest severity and the counts', () => {
    const wrapper = detected()
    const tiles = wrapper.findAll('.stat-tile').map((tile) => tile.text())
    expect(tiles).toEqual(
      expect.arrayContaining([
        expect.stringContaining('SCORE6'),
        expect.stringContaining('PROCESSES5'),
        expect.stringContaining('FILES WRITTEN11'),
        expect.stringContaining('REGISTRY KEYS WRITTEN6'),
        expect.stringContaining('DNS3'),
        expect.stringContaining('HOSTS2'),
        expect.stringContaining('TCP4'),
        expect.stringContaining('DURATION1m 12s'),
      ]),
    )
    const severities = wrapper.findAllComponents(SeverityBadge)
    expect(severities[0]!.props('severity')).toBe('high')
  })

  it('lists the signatures with the most severe first', () => {
    const rows = detected().findAll('.signature-row')
    expect(rows.map((row) => row.find('.signature-row__name').text())).toEqual([
      'injection_rwx',
      'dead_connect',
      'creates_exe',
    ])
    expect(rows[0]!.text()).toContain('Allocates read-write-execute memory')
  })

  it('lists the ATT&CK techniques with the signatures that raised them', () => {
    const techniques = detected().findAll('.technique')
    expect(techniques.map((technique) => technique.find('.technique__id').text())).toEqual(['T1055', 'T1071'])
    expect(techniques[0]!.text()).toContain('injection_rwx')
  })

  it('lists the detected families', () => {
    expect(detected().text()).toContain('emotet')
  })

  it('says so explicitly when nothing was detected', () => {
    const wrapper = mountTab(
      analysisWithStatus('done', { score: 0, max_severity: null, summary: NO_DETECTIONS_SUMMARY }),
    )
    expect(wrapper.text()).toContain('no detections')
    expect(wrapper.find('.signature-row').exists()).toBe(false)
    expect(wrapper.find('.technique').exists()).toBe(false)
  })

  it('still renders when the stored summary is missing', () => {
    const wrapper = mountTab(analysisWithStatus('done', { summary: null }))
    expect(wrapper.text()).toContain('no detections')
    expect(wrapper.find('.stat-tile').exists()).toBe(true)
  })
})

describe('AnalysisSummaryTab terminal without a report', () => {
  it('says there is no report for a failed analysis', () => {
    expect(mountTab(analysisWithStatus('failed', { error: 'boom' })).text()).toContain('no report')
  })

  it('says the report could not be read for report_failed', () => {
    expect(mountTab(analysisWithStatus('report_failed', { error: 'bad json' })).text()).toContain(
      'report could not be read',
    )
  })

  it('says a cancelled analysis never ran', () => {
    expect(mountTab(analysisWithStatus('cancelled', { started_at: null })).text()).toContain('cancelled')
  })
})

describe('AnalysisSummaryTab events by lane', () => {
  const withLanes = (lane_counts?: Record<string, number>) =>
    mountTab(analysisWithStatus('done', { summary: { ...DETECTIONS_SUMMARY, lane_counts } }))

  it('draws a bar per lane that has events, with direct labels', () => {
    const wrapper = withLanes({ api: 472, network: 217, process: 15, file: 0 })
    const rows = wrapper.findAll('.lane-bar').map((row) => row.text())
    expect(rows).toEqual([expect.stringContaining('PROCESS'), expect.stringContaining('NETWORK'), expect.stringContaining('API')])
    expect(rows[2]).toContain('472')
  })

  it('has no lane section when the summary carries no lane counts', () => {
    const wrapper = withLanes(undefined)
    expect(wrapper.find('.lane-bar').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('EVENTS BY LANE')
  })
})

describe('AnalysisSummaryTab screenshots', () => {
  it('shows the screenshot strip of a done analysis', async () => {
    const wrapper = mountTab(analysisWithStatus('done', { id: 45, summary: DETECTIONS_SUMMARY }))
    await flushPromises()
    expect(artifactsMock).toHaveBeenCalledWith(expect.objectContaining({ path: { analysis_id: 45 } }))
    expect(wrapper.findAll('.screenshot-strip__thumb')).toHaveLength(3)
  })

  it('still renders everything else when the artifacts request fails', async () => {
    artifactsMock.mockResolvedValue({ data: undefined, error: { error: { message: 'boom' } } } as never)
    const wrapper = mountTab(analysisWithStatus('done', { summary: DETECTIONS_SUMMARY }))
    await flushPromises()
    expect(wrapper.text()).toContain('failed to load: boom')
    expect(wrapper.text()).toContain('SIGNATURES')
    expect(wrapper.findAll('.stat-tile').length).toBeGreaterThan(0)
  })

  it.each(['queued', 'starting', 'running', 'processing', 'ingesting', 'failed', 'report_failed', 'cancelled'] as const)(
    'does not ask for artifacts while the analysis is %s',
    async (status) => {
      mountTab(analysisWithStatus(status))
      await flushPromises()
      expect(artifactsMock).not.toHaveBeenCalled()
    },
  )
})
