import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import LiveDetectionsPanel from '@/components/LiveDetectionsPanel.vue'
import { liveDetectionOf, type LiveDetection } from '@/services/live-detections'
import { sigmaAlert } from './live-fixtures'

function detection(overrides: Parameters<typeof sigmaAlert>[0] = {}): LiveDetection {
  return liveDetectionOf(sigmaAlert(overrides))!
}

function mountPanel(detections: LiveDetection[] = []) {
  return mount(LiveDetectionsPanel, { global: { plugins: [Quasar] }, props: { detections } })
}

describe('LiveDetectionsPanel empty', () => {
  it('says why there is nothing: Sigma rules match as events arrive, CAPE signatures run after the analysis', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.pane-heading').text()).toBe('DETECTIONS')
    expect(wrapper.text()).toContain('none yet')
    expect(wrapper.text()).toContain('Sigma rules match as events arrive')
    expect(wrapper.text()).toContain('CAPE signatures run after the analysis')
    expect(wrapper.find('.live-detections__item').exists()).toBe(false)
  })
})

describe('LiveDetectionsPanel with detections', () => {
  it('counts them in the heading', () => {
    expect(mountPanel([detection({ id: 'a' }), detection({ id: 'b' })]).find('.pane-heading').text()).toBe('DETECTIONS (2)')
  })

  it('lists the newest first', () => {
    const wrapper = mountPanel([
      detection({ id: 'old', '@timestamp': '2026-10-13T15:39:51.000Z' }),
      detection({ id: 'new', '@timestamp': '2026-10-13T15:39:59.000Z' }),
    ])
    expect(wrapper.findAll('.live-detections__item').map((item) => item.attributes('data-detection-id'))).toEqual(['new', 'old'])
  })

  it('shows the severity badge, the ruleset, the rule name, the technique ids, the process and the time', () => {
    const item = mountPanel([detection({ severity: 3 })]).find('.live-detections__item')
    expect(item.find('.severity-badge').text()).toContain('HIGH')
    expect(item.find('.live-detections__ruleset').text()).toBe('SIGMA')
    expect(item.find('.live-detections__name').text()).toBe('Tartarus Self-Test Registry Marker Written')
    expect(item.find('.live-detections__techniques').text()).toBe('T1112')
    expect(item.find('.process-chip').text()).toBe('benign.exe (9708)')
    expect(item.find('.live-detections__time').text()).toBe('15:39:51.100')
  })

  it('leaves out the techniques line for a rule that has none', () => {
    const alert = sigmaAlert()
    delete (alert as Partial<typeof alert>).threat
    const item = mountPanel([liveDetectionOf(alert)!]).find('.live-detections__item')
    expect(item.find('.live-detections__techniques').exists()).toBe(false)
  })

  it('lets a long rule name wrap and keeps the whole text as its title', () => {
    const name = `proc_creation_win_${'unbroken_rule_name_segment_'.repeat(6)}end`
    const item = mountPanel([detection({ rule: { id: 'x', name, ruleset: 'sigma' } })]).find('.live-detections__name')
    expect(item.text()).toBe(name)
    expect(item.attributes('title')).toBe(name)
  })

  it('does not show the empty line once there is a detection', () => {
    expect(mountPanel([detection()]).text()).not.toContain('none yet')
  })
})
