import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import type { AnalysisRead } from '@/api'
import AnalysesTable from '@/components/AnalysesTable.vue'
import AnalysisRowMenu from '@/components/AnalysisRowMenu.vue'
import { formatTimestamp } from '@/services/format-time'

const SUBMITTED_AT = new Date(2026, 9, 12, 14, 3).toISOString()

function analysis(overrides: Partial<AnalysisRead> = {}): AnalysisRead {
  return {
    id: 42,
    sample_sha256: '9f2c4b7a1d3e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7a1',
    filename: 'invoice.exe',
    cape_task_id: 7,
    status: 'done',
    phase: 'done',
    options: {},
    score: 8.5,
    max_severity: 'high',
    detected_families: [],
    event_count: 0,
    disk_bytes: 0,
    error: null,
    submitted_at: SUBMITTED_AT,
    started_at: null,
    finished_at: null,
    summary: null,
    tags: [],
    ...overrides,
  } as AnalysisRead
}

function mountTable(analyses: AnalysisRead[]) {
  return mount(AnalysesTable, { global: { plugins: [Quasar] }, props: { analyses } })
}

describe('AnalysesTable', () => {
  it('shows one row per analysis with id, name, hash prefix, time, status, score and severity', () => {
    const wrapper = mountTable([analysis()])
    const row = wrapper.find('tbody tr')
    expect(row.text()).toContain('42')
    expect(row.text()).toContain('invoice.exe')
    expect(row.text()).toContain('9f2c4b7a…')
    expect(row.text()).not.toContain('9f2c4b7a1d3e')
    expect(row.text()).toContain(formatTimestamp(SUBMITTED_AT))
    expect(row.find('.status-badge').text()).toContain('DONE')
    expect(row.text()).toContain('8.5')
    expect(row.find('.severity-badge').text()).toContain('HIGH')
  })

  it('shows dashes instead of a score and severity while the analysis has none', () => {
    const wrapper = mountTable([analysis({ status: 'running', score: null, max_severity: null })])
    const row = wrapper.find('tbody tr')
    expect(row.find('.severity-badge').exists()).toBe(false)
    expect(row.findAll('.cell-empty')).toHaveLength(2)
  })

  it('lists the first tag of each analysis in the TAGS column, with the others folded into +N', () => {
    const wrapper = mountTable([analysis({ tags: ['emotet', 'phishing'] }), analysis({ id: 43, tags: [] })])
    expect(wrapper.findAll('th').map((header) => header.text())).toContain('TAGS')
    const [tagged, untagged] = wrapper.findAll('tbody tr')
    expect(tagged!.findAll('.tag-chip').map((chip) => chip.text())).toEqual(['emotet'])
    expect(tagged!.get('.tag-list__more').attributes('title')).toBe('phishing')
    expect(untagged!.find('.tag-chip').exists()).toBe(false)
  })

  it('drops the TAGS column on a narrow screen, with the other optional columns', () => {
    const wrapper = mountTable([analysis({ tags: ['emotet'] })])
    expect(wrapper.findAll('th').find((header) => header.text() === 'TAGS')!.classes()).toContain('col-optional')
    expect(wrapper.get('.col-tags').classes()).toContain('col-optional')
  })

  it('counts every tag after the first in the +N', () => {
    const wrapper = mountTable([analysis({ tags: ['a', 'b', 'c', 'd'] })])
    expect(wrapper.findAll('tbody .tag-chip')).toHaveLength(1)
    expect(wrapper.get('.tag-list__more').text()).toBe('+3')
  })

  it('puts the guest chip under the file name, so the table gains no column', () => {
    const wrapper = mountTable([analysis({ guest: 'lab1', guest_badges: ['DEFENDER OFF'] })])
    const fileCell = wrapper.findAll('tbody td').find((cell) => cell.find('.cell-filename').exists())!
    expect(fileCell.find('.guest-chip__name').text()).toBe('lab1')
    expect(fileCell.find('.guest-chip__badge').text()).toBe('DEFENDER OFF')
    expect(wrapper.findAll('th')).toHaveLength(9)
  })

  it('shows no guest chip for an analysis from before guests', () => {
    const wrapper = mountTable([analysis({ guest: null })])
    expect(wrapper.find('.guest-chip').exists()).toBe(false)
  })

  it('keeps the full file name and hash reachable on hover when they are truncated', () => {
    const filename = `${'very-long-name-'.repeat(8)}.exe`
    const wrapper = mountTable([analysis({ filename })])
    expect(wrapper.find('.cell-filename').attributes('title')).toBe(filename)
    expect(wrapper.find('.cell-sha').attributes('title')).toBe(analysis().sample_sha256)
  })

  it('emits open with the id when a row is clicked or activated by keyboard', async () => {
    const wrapper = mountTable([analysis({ id: 7 }), analysis({ id: 8 })])
    await wrapper.findAll('tbody tr')[1]!.trigger('click')
    await wrapper.findAll('tbody tr')[0]!.trigger('keydown.enter')
    expect(wrapper.emitted('open')).toEqual([[8], [7]])
  })

  it('offers cancel, not delete, for a queued or active analysis', () => {
    for (const status of ['queued', 'starting', 'running', 'processing', 'ingesting'] as const) {
      const wrapper = mountTable([analysis({ status })])
      expect(wrapper.find('[aria-label="Cancel analysis 42"]').exists(), status).toBe(true)
      expect(wrapper.find('[aria-label="Delete analysis 42"]').exists(), status).toBe(false)
    }
  })

  it('offers delete, not cancel, for a finished analysis', () => {
    for (const status of ['done', 'failed', 'report_failed', 'cancelled'] as const) {
      const wrapper = mountTable([analysis({ status })])
      expect(wrapper.find('[aria-label="Delete analysis 42"]').exists(), status).toBe(true)
      expect(wrapper.find('[aria-label="Cancel analysis 42"]').exists(), status).toBe(false)
    }
  })

  it('emits remove or cancel without also opening the row', async () => {
    const wrapper = mountTable([analysis({ id: 1, status: 'done' }), analysis({ id: 2, status: 'queued' })])
    await wrapper.find('[aria-label="Delete analysis 1"]').trigger('click')
    await wrapper.find('[aria-label="Cancel analysis 2"]').trigger('click')
    expect(wrapper.emitted('remove')).toEqual([[1]])
    expect(wrapper.emitted('cancel')).toEqual([[2]])
    expect(wrapper.emitted('open')).toBeUndefined()
  })

  it('has a row menu on every row, and passes what it asks for up as table events', async () => {
    const wrapper = mountTable([analysis({ id: 1 }), analysis({ id: 2, status: 'running' })])
    const menus = wrapper.findAllComponents(AnalysisRowMenu)
    expect(menus.map((menu) => menu.props('analysis').id)).toEqual([1, 2])

    menus[0]!.vm.$emit('open', 1)
    menus[0]!.vm.$emit('reingest', 1)
    menus[0]!.vm.$emit('remove', 1)
    menus[1]!.vm.$emit('cancel', 2)

    expect(wrapper.emitted('open')).toEqual([[1]])
    expect(wrapper.emitted('reingest')).toEqual([[1]])
    expect(wrapper.emitted('remove')).toEqual([[1]])
    expect(wrapper.emitted('cancel')).toEqual([[2]])
  })
})
