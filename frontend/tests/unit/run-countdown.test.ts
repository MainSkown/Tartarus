import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import RunCountdown from '@/components/RunCountdown.vue'

const mountCountdown = (props: { seconds: number | null; interactive?: boolean; running?: boolean }) =>
  mount(RunCountdown, { global: { plugins: [Quasar] }, props: { interactive: false, running: false, ...props } })

describe('RunCountdown', () => {
  it('shows the duration with no warning for a run that is not interactive', () => {
    const wrapper = mountCountdown({ seconds: 25, running: true })
    expect(wrapper.text()).toBe('25s')
    expect(wrapper.classes()).not.toContain('run-countdown--warning')
  })

  it('takes the warning style in the last 30 seconds of an interactive run', () => {
    const wrapper = mountCountdown({ seconds: 25, interactive: true, running: true })
    expect(wrapper.classes()).toContain('run-countdown--warning')
  })

  it('says ending at zero while an interactive run is still running', () => {
    const wrapper = mountCountdown({ seconds: 0, interactive: true, running: true })
    expect(wrapper.text()).toBe('ending')
    expect(wrapper.classes()).toContain('run-countdown--warning')
  })

  it('shows a dash when there is no time', () => {
    expect(mountCountdown({ seconds: null, interactive: true, running: true }).text()).toBe('–')
  })
})
