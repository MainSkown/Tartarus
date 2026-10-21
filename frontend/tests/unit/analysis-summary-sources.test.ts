import { flushPromises, mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisRead, DefenderThreat, DefenderVerdict, MemorySummary, ReportSummary } from '@/api'
import { analysisWithStatus, DETECTIONS_SUMMARY } from './analysis-fixtures'
import { ARTIFACTS_VIEW } from './detections-fixtures'

vi.mock('@/api', () => ({ viewsArtifacts: vi.fn() }))

const { viewsArtifacts } = await import('@/api')
const AnalysisSummaryTab = (await import('@/components/AnalysisSummaryTab.vue')).default

beforeEach(() => {
  vi.mocked(viewsArtifacts).mockResolvedValue({ data: ARTIFACTS_VIEW, error: undefined } as never)
})

const SAMPLE_PATH = 'C:\\Users\\Alice\\AppData\\Local\\Temp\\321\\eicar.com'

function threat(overrides: Partial<DefenderThreat> = {}): DefenderThreat {
  return {
    detection_id: '{A}',
    threat_id: 2147519003,
    name: 'Virus:DOS/EICAR_Test_File',
    severity: 4,
    category_id: 42,
    scope: 'sample',
    path: SAMPLE_PATH,
    process: 'C:\\Python311\\pythonw.exe',
    user: null,
    detected_at: '2026-10-12T09:14:31Z',
    action: 'Quarantine',
    outcome: 'removed',
    removed_at: '2026-10-12T09:14:44Z',
    ...overrides,
  }
}

function verdict(overrides: Partial<DefenderVerdict> = {}): DefenderVerdict {
  return { status: 'removed', sample_removed: true, blocked_before_run: false, threats: [threat()], ...overrides }
}

function mountTab(summary: Partial<ReportSummary>, overrides: Partial<AnalysisRead> = {}) {
  const analysis = analysisWithStatus('done', {
    guest: 'lab5',
    guest_badges: ['DEFENDER ON', 'SYSMON'],
    summary: { ...DETECTIONS_SUMMARY, ...summary },
    ...overrides,
  })
  return mount(AnalysisSummaryTab, { global: { plugins: [Quasar] }, props: { analysis } })
}

describe('Defender verdict', () => {
  it('says which file Defender removed and how, with its threat, severity and times', () => {
    const wrapper = mountTab({ defender: verdict({ sample_removed: false, threats: [threat({ scope: 'dropped', path: 'C:\\Users\\Public\\tt-dropped.txt' })] }) })
    const text = wrapper.find('.defender-verdict').text()
    expect(text).toContain('Defender removed a file the sample dropped')
    expect(text).toContain('Virus:DOS/EICAR_Test_File')
    expect(text).toContain('DROPPED FILE')
    expect(text).toContain('tt-dropped.txt')
    expect(text).toContain('CRITICAL')
    expect(text).toContain('Quarantine')
    expect(text).toContain('removed')
    expect(text).toContain('2026-10-12 09:14:31 UTC')
    expect(text).toContain('2026-10-12 09:14:44 UTC')
  })

  it('says Defender removed the sample when the sample itself went', () => {
    const wrapper = mountTab({ defender: verdict() })
    expect(wrapper.find('.defender-verdict').text()).toContain('Defender removed the sample')
    expect(wrapper.find('.defender-verdict').text()).toContain('SAMPLE')
  })

  it('makes a sample removed before it ran the headline of the tab, above the counts', () => {
    const wrapper = mountTab(
      { defender: verdict({ blocked_before_run: true }), process_count: 0 },
    )
    const section = wrapper.find('.defender-verdict')
    expect(section.text()).toContain('Defender removed the sample before it ran: nothing was executed')
    expect(section.classes()).toContain('defender-verdict--prominent')
    const order = [...wrapper.element.querySelectorAll('.defender-verdict, .stat-tile')]
    expect(order[0]).toBe(section.element)
  })

  it('places an ordinary verdict among the detections, below the counts', () => {
    const wrapper = mountTab({ defender: verdict() })
    const section = wrapper.find('.defender-verdict')
    expect(section.classes()).not.toContain('defender-verdict--prominent')
    const order = [...wrapper.element.querySelectorAll('.defender-verdict, .stat-tile, .signature-row')]
    expect(order.indexOf(section.element)).toBeGreaterThan(order.findIndex((node) => node.classList.contains('stat-tile')))
    expect(order.indexOf(section.element)).toBeLessThan(order.findIndex((node) => node.classList.contains('signature-row')))
  })

  it('says a detection was not confirmed removed', () => {
    const wrapper = mountTab({
      defender: verdict({ status: 'detected', sample_removed: false, threats: [threat({ outcome: 'pending', action: 'Unknown', removed_at: null })] }),
    })
    const text = wrapper.find('.defender-verdict').text()
    expect(text).toContain('Defender detected a threat')
    expect(text).toContain('still be on disk or not confirmed removed')
    expect(text).toContain('Virus:DOS/EICAR_Test_File')
    expect(text).not.toContain('2026-10-12 09:14:44 UTC')
  })

  it('says Defender tried and could not remove it', () => {
    const wrapper = mountTab({
      defender: verdict({ status: 'failed', sample_removed: false, threats: [threat({ outcome: 'failed', removed_at: null })] }),
    })
    expect(wrapper.find('.defender-verdict').text()).toContain('Defender could not remove')
    expect(wrapper.find('.defender-verdict').text()).toContain('removal failed')
  })

  it('says plainly that a clean run had no detection, with no threat rows', () => {
    const wrapper = mountTab({ defender: verdict({ status: 'clean', sample_removed: false, threats: [] }) })
    expect(wrapper.find('.defender-verdict').text()).toContain('Defender detected nothing')
    expect(wrapper.find('.defender-threat').exists()).toBe(false)
  })

  it('says the verdict is unavailable when the guest left no Defender log', () => {
    const wrapper = mountTab({ defender: verdict({ status: 'no_export', sample_removed: false, threats: [] }) })
    expect(wrapper.find('.defender-verdict').text()).toContain('Defender verdict unavailable')
  })

  it('shows no verdict for a guest with Defender off, even when the summary says clean', () => {
    const wrapper = mountTab(
      { defender: verdict({ status: 'clean', sample_removed: false, threats: [] }) },
      { guest_badges: ['DEFENDER OFF'] },
    )
    expect(wrapper.find('.defender-verdict').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Defender detected nothing')
  })

  it('shows no verdict for an analysis whose guest badges are unknown', () => {
    const wrapper = mountTab({ defender: verdict() }, { guest_badges: [] })
    expect(wrapper.find('.defender-verdict').exists()).toBe(false)
  })

  it('shows no verdict when the summary has none', () => {
    expect(mountTab({ defender: null }).find('.defender-verdict').exists()).toBe(false)
  })

  it('gives a long path its full text on hover and a button to copy it', () => {
    const longPath = `C:\\Users\\Alice\\AppData\\Local\\${'Deeply\\Nested\\'.repeat(12)}payload.dll`
    const wrapper = mountTab({ defender: verdict({ threats: [threat({ path: longPath })] }) })
    expect(wrapper.find('.defender-threat__path').attributes('title')).toBe(longPath)
    expect(wrapper.find('.defender-threat__file').text()).toBe('payload.dll')
    expect(wrapper.find('.defender-threat .copy-button').attributes('aria-label')).toBe('Copy path')
  })

  it('lists every threat, one row each', () => {
    const threats = Array.from({ length: 10 }, (_, index) => threat({ detection_id: `{${index}}`, name: `Threat.${index}` }))
    const wrapper = mountTab({ defender: verdict({ threats }) })
    expect(wrapper.findAll('.defender-threat')).toHaveLength(10)
  })

  it('copes with a threat that has no name or path', () => {
    const wrapper = mountTab({ defender: verdict({ threats: [threat({ name: null, path: null, detected_at: null })] }) })
    expect(wrapper.find('.defender-threat').text()).toContain('unknown threat')
    expect(wrapper.find('.defender-threat__path').exists()).toBe(false)
  })
})

describe('Hidden Sysmon events', () => {
  it('says how many background events were hidden, with the reasons in a tooltip source', () => {
    const wrapper = mountTab({ hidden_events: { 'windows-background': 410, 'cape-tooling': 12 } })
    expect(wrapper.find('.hidden-events').text()).toBe('422 background events from Windows were hidden (Sysmon)')
  })

  it('uses the singular for one event', () => {
    const wrapper = mountTab({ hidden_events: { 'windows-background': 1 } })
    expect(wrapper.find('.hidden-events').text()).toBe('1 background event from Windows was hidden (Sysmon)')
  })

  it('is absent when nothing was hidden', () => {
    expect(mountTab({ hidden_events: {} }).find('.hidden-events').exists()).toBe(false)
    expect(mountTab({ hidden_events: { 'windows-background': 0 } }).find('.hidden-events').exists()).toBe(false)
  })
})

describe('Memory status', () => {
  const memory = (overrides: Partial<MemorySummary> = {}): MemorySummary => ({
    dump_taken: true,
    findings: 'ok',
    error: null,
    dump_bytes: 4 * 1024 ** 3,
    dump_deleted: true,
    ...overrides,
  })

  it('says the dump was taken and how big, that the findings are in and the dump deleted', () => {
    const wrapper = mountTab({ memory: memory(), lane_counts: { memory: 37, api: 5 } })
    const text = wrapper.find('.memory-status').text()
    expect(text).toContain('4 GB')
    expect(text).toContain('37 memory events')
    expect(text).toContain('deleted after the findings')
  })

  it('reads the findings without a count when the summary has no lane counts', () => {
    const text = mountTab({ memory: memory() }).find('.memory-status').text()
    expect(text).toContain('findings read')
    expect(text).not.toContain('memory events')
  })

  it('shows the error CAPE gave when no dump was taken', () => {
    const error = 'CAPE took no memory dump: it is below its free-space floor'
    const wrapper = mountTab({ memory: memory({ dump_taken: false, findings: 'unavailable', error, dump_bytes: null, dump_deleted: null }) })
    const text = wrapper.find('.memory-status').text()
    expect(text).toContain('not taken')
    expect(text).toContain('no findings: there was no dump to read')
    expect(text).toContain(error)
    expect(text).not.toContain('kept')
  })

  it('shows the error when Volatility failed', () => {
    const wrapper = mountTab({ memory: memory({ findings: 'failed', error: 'volatility3 exited with 1' }) })
    expect(wrapper.find('.memory-status').text()).toContain('findings failed')
    expect(wrapper.find('.memory-status').text()).toContain('volatility3 exited with 1')
  })

  it('says a dump that could not be deleted is still there', () => {
    expect(mountTab({ memory: memory({ dump_deleted: false }) }).find('.memory-status').text()).toContain('could not be deleted')
  })

  it('says a dump the analyst asked to keep was kept', () => {
    expect(mountTab({ memory: memory({ dump_deleted: null }) }).find('.memory-status').text()).toContain('kept')
  })

  it('is absent without a memory summary', () => {
    expect(mountTab({ memory: null }).find('.memory-status').exists()).toBe(false)
  })
})

describe('A summary from before the sources', () => {
  it('renders no Defender, hidden-events or memory block', async () => {
    const wrapper = mountTab({}, { guest_badges: ['DEFENDER ON'] })
    await flushPromises()
    expect(wrapper.find('.defender-verdict').exists()).toBe(false)
    expect(wrapper.find('.hidden-events').exists()).toBe(false)
    expect(wrapper.find('.memory-status').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('MEMORY')
    expect(wrapper.text()).not.toContain('DEFENDER')
  })
})

describe('Ingest warnings', () => {
  const WARNING = 'Sysmon events were not exported: the guest did not answer within 120 s'

  it('shows each warning of the ingest as an alert above the tiles, so an empty Sysmon lane is not read as a quiet run', () => {
    const wrapper = mountTab({ warnings: [WARNING, 'Windows Defender events were not exported: the guest did not answer within 30 s'] })
    expect(wrapper.findAll('.analysis-warnings [role="alert"]')).toHaveLength(2)
    expect(wrapper.findAll('.analysis-warnings .live-notice__text').map((notice) => notice.text())).toEqual([WARNING, 'Windows Defender events were not exported: the guest did not answer within 30 s'])
    expect(wrapper.find('.analysis-warnings').element.compareDocumentPosition(wrapper.find('.analysis-summary__tiles').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows no notice when the ingest had nothing to warn about', () => {
    expect(mountTab({ warnings: [] }).find('.analysis-warnings').exists()).toBe(false)
    expect(mountTab({}).find('.analysis-warnings').exists()).toBe(false)
  })
})
