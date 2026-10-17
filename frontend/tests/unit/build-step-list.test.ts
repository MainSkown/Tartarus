import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BuildStep, StepProgress } from '@/api'
import BuildStepList from '@/components/guest/BuildStepList.vue'
import { STEP_STATUSES, stepMeta } from '@/services/guest-build'

function step(name: string, status: StepProgress, overrides: Partial<BuildStep> = {}): BuildStep {
  return { name, status, weight: 1, timeout_s: 60, desktop: false, progress: 0, ...overrides }
}

const mountList = (steps: BuildStep[]) => mount(BuildStepList, { global: { plugins: [Quasar] }, props: { steps } })

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-17T10:10:00Z'))
})
afterEach(() => vi.useRealTimers())

describe('BuildStepList', () => {
  it('lists every step in order with its humanised name', () => {
    const wrapper = mountList([step('preflight', 'succeeded'), step('tamper-off', 'pending'), step('snapshot', 'pending')])
    expect(wrapper.findAll('li').map((row) => row.find('.build-step__name').text())).toEqual(['PREFLIGHT', 'TAMPER OFF', 'SNAPSHOT'])
  })

  it.each(STEP_STATUSES)('shows the %s status with its icon and its label, not by colour alone', (status) => {
    const wrapper = mountList([step('install', status)])
    const row = wrapper.find('li')
    expect(row.attributes('data-status')).toBe(status)
    expect(row.find('.build-step__status').text()).toBe(stepMeta(status).label)
    if (status === 'running') expect(row.find('.loader').exists()).toBe(true)
    else expect(row.find('.q-icon').text()).toBe(stepMeta(status).icon)
  })

  it('shows how long finished steps took and how long a running step has taken so far', () => {
    const wrapper = mountList([
      step('define', 'succeeded', { started: '2026-10-17T10:00:00Z', finished: '2026-10-17T10:00:12Z' }),
      step('install', 'running', { started: '2026-10-17T10:05:00Z' }),
      step('provision', 'pending'),
    ])
    const durations = wrapper.findAll('li').map((row) => row.find('.build-step__duration').exists() && row.find('.build-step__duration').text())
    expect(durations).toEqual(['12s', '5m 0s', false])
  })

  it('counts a running step up as time passes', async () => {
    const wrapper = mountList([step('install', 'running', { started: '2026-10-17T10:09:50Z' })])
    expect(wrapper.find('.build-step__duration').text()).toBe('10s')
    await vi.advanceTimersByTimeAsync(5_000)
    expect(wrapper.find('.build-step__duration').text()).toBe('15s')
  })

  it('names the exit code of a failed step', () => {
    const wrapper = mountList([step('provision', 'failed', { exit_code: 2 })])
    expect(wrapper.find('li').text()).toContain('exit 2')
  })

  it('marks the failed step so that it stands out, and a desktop step as showing one', () => {
    const wrapper = mountList([step('install', 'succeeded', { desktop: true }), step('provision', 'failed')])
    expect(wrapper.findAll('li')[1]!.classes()).toContain('build-step--failed')
    expect(wrapper.findAll('li')[0]!.find('[data-step-desktop]').exists()).toBe(true)
    expect(wrapper.findAll('li')[1]!.find('[data-step-desktop]').exists()).toBe(false)
  })

  it('shows a calm line for a build whose steps are not known yet', () => {
    expect(mountList([]).text()).toContain('no steps yet')
  })
})
