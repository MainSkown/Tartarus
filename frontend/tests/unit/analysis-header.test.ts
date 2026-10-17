import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { Notify, Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisStatus } from '@/api'
import AnalysisHeader from '@/components/AnalysisHeader.vue'
import ExportMenu from '@/components/ExportMenu.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TagInput from '@/components/TagInput.vue'
import { ANALYSIS_TARGET } from '@/stores/annotations'
import { ANALYSIS_STATUSES, isActiveStatus } from '@/services/analysis-status'
import { analysisFixture, analysisWithStatus, SHA256 } from './analysis-fixtures'

function mountHeader(analysis = analysisFixture(), busy = false) {
  return mount(AnalysisHeader, { global: { plugins: [Quasar, createPinia()] }, props: { analysis, busy } })
}

const writeText = vi.fn().mockResolvedValue(undefined)

beforeEach(() => {
  vi.clearAllMocks()
  Notify.create = vi.fn()
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
})

describe('AnalysisHeader identity', () => {
  it('shows the id, filename, full hash and status badge', () => {
    const wrapper = mountHeader()
    expect(wrapper.text()).toContain('#42')
    expect(wrapper.find('.analysis-header__filename').text()).toBe('invoice.exe')
    expect(wrapper.find('.analysis-header__hash').text()).toContain(SHA256)
    expect(wrapper.findComponent(StatusBadge).props('status')).toBe('done')
  })

  it('keeps a long filename and the full hash reachable when the text is cut off', () => {
    const filename = `${'long-name-'.repeat(20)}.exe`
    const wrapper = mountHeader(analysisFixture({ filename }))
    expect(wrapper.find('.analysis-header__filename').attributes('title')).toBe(filename)
    expect(wrapper.find('.analysis-header__hash').attributes('title')).toBe(SHA256)
  })

  it('copies the full SHA-256 and confirms with a toast', async () => {
    const wrapper = mountHeader()
    await wrapper.find('.analysis-header__copy').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(SHA256)
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-success' }))
  })
})

describe('AnalysisHeader guest', () => {
  it('shows the guest the analysis ran on with its badges', () => {
    const wrapper = mountHeader(analysisFixture({ guest: 'lab1', guest_badges: ['DEFENDER OFF'] }))
    const guest = wrapper.find('.analysis-header__guest')
    expect(guest.find('.guest-chip__name').text()).toBe('lab1')
    expect(guest.find('.guest-chip__badge').text()).toBe('DEFENDER OFF')
  })

  it('shows a deleted guest by its stored name alone', () => {
    const wrapper = mountHeader(analysisFixture({ guest: 'lab9', guest_badges: [] }))
    expect(wrapper.find('.analysis-header__guest .guest-chip__name').text()).toBe('lab9')
    expect(wrapper.find('.guest-chip__badge').exists()).toBe(false)
  })

  it('shows no guest for an analysis from before guests', () => {
    expect(mountHeader(analysisFixture({ guest: null })).find('.analysis-header__guest').exists()).toBe(false)
  })
})

describe('AnalysisHeader tags', () => {
  it('edits the tags of the analysis, whatever its status', () => {
    for (const status of ['running', 'done', 'failed'] as const) {
      const input = mountHeader(analysisWithStatus(status)).findComponent(TagInput)
      expect(input.props()).toMatchObject({ target: ANALYSIS_TARGET, editable: true })
    }
  })
})

describe('AnalysisHeader timing', () => {
  it('shows submitted and started in UTC and the duration of a finished run', () => {
    const text = mountHeader().text()
    expect(text).toContain('2026-10-13 10:00:00 UTC')
    expect(text).toContain('2026-10-13 10:00:05 UTC')
    expect(text).toContain('1m 12s')
  })

  it('shows only the submission while the analysis has not started', () => {
    const wrapper = mountHeader(analysisWithStatus('queued', { started_at: null, finished_at: null }))
    expect(wrapper.text()).toContain('2026-10-13 10:00:00 UTC')
    expect(wrapper.find('.analysis-header__started').exists()).toBe(false)
    expect(wrapper.find('.analysis-header__duration').exists()).toBe(false)
  })

  it('shows no duration while the run is still going', () => {
    const wrapper = mountHeader(analysisWithStatus('running', { finished_at: null }))
    expect(wrapper.find('.analysis-header__started').exists()).toBe(true)
    expect(wrapper.find('.analysis-header__duration').exists()).toBe(false)
  })
})

describe('AnalysisHeader banner', () => {
  it.each(['failed', 'report_failed'] as AnalysisStatus[])('shows the error of a %s analysis', (status) => {
    const wrapper = mountHeader(analysisWithStatus(status, { error: 'CAPE went away' }))
    const banner = wrapper.find('[role="alert"]')
    expect(banner.text()).toContain('CAPE went away')
  })

  it('falls back to a generic message when the failure carries no error', () => {
    const wrapper = mountHeader(analysisWithStatus('failed', { error: null }))
    expect(wrapper.find('[role="alert"]').text()).toContain('no error message')
  })

  it.each(ANALYSIS_STATUSES.filter((status) => status !== 'failed' && status !== 'report_failed'))(
    'has no banner for %s',
    (status) => {
      expect(mountHeader(analysisWithStatus(status)).find('[role="alert"]').exists()).toBe(false)
    },
  )
})

describe('AnalysisHeader actions', () => {
  it('offers cancel only while queued', () => {
    for (const status of ANALYSIS_STATUSES) {
      const wrapper = mountHeader(analysisWithStatus(status))
      expect(wrapper.find('.analysis-header__cancel').exists(), status).toBe(status === 'queued')
    }
  })

  it('offers delete unless the analysis is on its way through CAPE', () => {
    for (const status of ANALYSIS_STATUSES) {
      const wrapper = mountHeader(analysisWithStatus(status))
      expect(wrapper.find('.analysis-header__delete').exists(), status).toBe(!isActiveStatus(status))
    }
  })

  it('emits cancel and delete', async () => {
    const queued = mountHeader(analysisWithStatus('queued'))
    await queued.find('.analysis-header__cancel').trigger('click')
    await queued.find('.analysis-header__delete').trigger('click')
    expect(queued.emitted('cancel')).toHaveLength(1)
    expect(queued.emitted('delete')).toHaveLength(1)
  })

  it('offers the Export menu for the analysis in every status, before the delete button', () => {
    for (const status of ANALYSIS_STATUSES) {
      const wrapper = mountHeader(analysisWithStatus(status, { id: 193 }))
      const menu = wrapper.findComponent(ExportMenu)
      expect(menu.exists(), status).toBe(true)
      expect(menu.props('analysis')).toMatchObject({ id: 193, status })
    }
    const actions = mountHeader().find('.analysis-header__actions')
    const order = actions.findAll('button').map((button) => button.text())
    expect(order).toEqual(['[EXPORT]', '[DELETE]'])
  })

  it('disables the actions while one is in flight', () => {
    const wrapper = mountHeader(analysisWithStatus('queued'), true)
    expect(wrapper.find('.analysis-header__cancel').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.analysis-header__delete').attributes('disabled')).toBeDefined()
  })
})

describe('AnalysisHeader countdown', () => {
  const NOW = '2026-10-13T10:00:00Z'
  const deadline = (seconds: number) => new Date(Date.parse(NOW) + seconds * 1000).toISOString()

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(Date.parse(NOW))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('counts down the time left of an interactive run that has a deadline', async () => {
    const wrapper = mountHeader(analysisWithStatus('running', { finished_at: null, options: { interactive: true }, deadline_at: deadline(180) }))
    expect(wrapper.find('.analysis-header__remaining').text()).toContain('3m 0s')
    await vi.advanceTimersByTimeAsync(5_000)
    expect(wrapper.find('.analysis-header__remaining').text()).toContain('2m 55s')
  })

  it('takes the new deadline when an extension moves it', async () => {
    const wrapper = mountHeader(analysisWithStatus('running', { finished_at: null, options: { interactive: true }, deadline_at: deadline(30) }))
    await wrapper.setProps({ analysis: analysisWithStatus('running', { finished_at: null, options: { interactive: true }, deadline_at: deadline(90) }) })
    expect(wrapper.find('.analysis-header__remaining').text()).toContain('1m 30s')
  })

  it('shows nothing for a run that is not interactive', () => {
    const wrapper = mountHeader(analysisWithStatus('running', { finished_at: null, deadline_at: deadline(180) }))
    expect(wrapper.find('.analysis-header__remaining').exists()).toBe(false)
  })

  it('shows nothing for an interactive run without a deadline yet', () => {
    const wrapper = mountHeader(analysisWithStatus('running', { finished_at: null, options: { interactive: true }, deadline_at: null }))
    expect(wrapper.find('.analysis-header__remaining').exists()).toBe(false)
  })

  it('shows nothing once the interactive run is over', () => {
    const wrapper = mountHeader(analysisWithStatus('processing', { options: { interactive: true }, deadline_at: deadline(-5) }))
    expect(wrapper.find('.analysis-header__remaining').exists()).toBe(false)
  })
})

